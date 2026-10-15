"""
宝妈指数 — 主流程
采集 → 分析 → 计算 → 存储 → 输出
"""
import os
import json
from datetime import datetime
from uuid import uuid4
from dataclasses import asdict
from pathlib import Path
from mom_index.provenance import (prepare_posts, build_definition, now_local, SCHEMA_VERSION, digest, assess_valid_quality)
from typing import Dict

from mom_index.collectors.guba_collector import collect_all as collect_guba, SECTORS, MAX_PAGES
from mom_index.collectors.xhs_collector import collect_all as collect_xhs
from mom_index.collectors.xueqiu_collector import collect_all as collect_xueqiu
from mom_index.analyzer.llm_analyzer import analyze_all
from mom_index.analyzer.signal import generate_signals
from mom_index.analyzer.index_calculator import (
    compute_sector_index, add_record, get_dashboard_data, save_history, load_history, SECTOR_NAMES
)
from mom_index.collectors.price_collector import fetch_all_prices
from mom_index.storage import save_posts, count_posts, seen_post_ids

DATA_DIR = os.environ.get("MOM_INDEX_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))


def publish_dashboard(dashboard, frontend_dir=None):
    """仅发布经过过滤的生产 JSON；不向前端复制历史原件与原始帖子。"""
    target = Path(frontend_dir or Path(__file__).parent / "frontend" / "data")
    target.mkdir(parents=True, exist_ok=True)
    (target / "dashboard_data.json").write_text(
        json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(publish=True):
    """执行生产采集；无论演示开关如何设置，模拟帖子均不可进入分析。"""
    started = now_local()
    run_id = uuid4().hex
    definition = build_definition(MAX_PAGES)
    all_posts = {key: [] for key in SECTORS}
    reports = {}
    for source, collector in [('guba', collect_guba), ('xhs', collect_xhs), ('xueqiu', collect_xueqiu)]:
        state = {'status': 'ok', 'sectors': {}}
        if source == 'xhs' and not os.environ.get('RNODE_API_KEY'):
            state['status'] = 'demo_only' if os.environ.get('XHS_ALLOW_MOCK') == '1' else 'disabled'
        if source == 'xueqiu' and os.environ.get('MOM_INDEX_ENABLE_XUEQIU') != '1':
            state['status'] = 'disabled'
        try:
            data = collector(report=state['sectors'])
            if state['status'] == 'ok' and not any(data.values()):
                state['status'] = 'empty'
            for sector, posts in data.items():
                if sector in all_posts:
                    all_posts[sector].extend(posts)
        except Exception as exc:
            state.update(status='failed', error_type=type(exc).__name__)
        reports[source] = state

    assessed_at = now_local()
    qualities = {}
    for sector, posts in all_posts.items():
        # 必须先查已见身份，再追加本轮原始存档。
        accepted, quality = prepare_posts(posts, assessed_at, seen_post_ids(sector))
        save_posts(sector, posts, run_id=run_id)
        all_posts[sector] = accepted
        state = reports['guba']['sectors'].get(sector, {})
        quality['collector_duplicates'] = state.get('duplicate_count', 0)
        quality['collector_parsed_count'] = state.get('parsed_count', 0)
        quality['collection_status'] = state.get('status', reports['guba']['status'])
        source_failures = [source for source, report in reports.items()
                           if report['status'] == 'failed' or report['sectors'].get(sector, {}).get('status') in ('failed', 'partial')]
        quality['failed_sources'] = source_failures
        if quality['collection_status'] in ('failed', 'partial', 'empty') or source_failures:
            quality.update(status='collection_failed', reasons=['启用来源采集失败、不完整或无有效响应'])
        qualities[sector] = quality

    analysis_results = analyze_all(all_posts)
    indices = {}
    for sector in SECTORS:
        results = analysis_results.get(sector, [])
        value = compute_sector_index(results)
        quality = assess_valid_quality(all_posts[sector], results, qualities[sector], assessed_at)
        qualities[sector] = quality
        sector_definition_id = digest([definition['id'], sorted({p.get('platform', 'unknown') for p in all_posts[sector]})])
        value.update(quality=quality, definition_id=sector_definition_id)
        if quality['status'] != 'ok':
            value['index'] = None
            value['interpretation'] = '数据不足，暂停情绪判断'
        indices[sector] = value

    prices = fetch_all_prices(SECTORS)
    provenance = {'schema_version': SCHEMA_VERSION, 'run_id': run_id,
                  'started_at': started.isoformat(), 'finished_at': now_local().isoformat(),
                  'mock_excluded': True, 'definition': definition, 'sources': reports,
                  'sampling_window': {'kind': 'board_snapshot', 'fresh_hours': 24},
                  'price_status': {key: 'available' if key in prices else 'missing' for key in SECTORS}}
    add_record(indices, analysis_results, prices, provenance=provenance)
    dashboard = get_dashboard_data()
    dashboard['signals'] = generate_signals(dashboard)
    root = Path(DATA_DIR)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'runs').mkdir(exist_ok=True)
    (root / 'runs' / f'{run_id}.json').write_text(
        json.dumps({'provenance': provenance, 'quality': qualities, 'sectors': indices,
                    'analysis': {key: [asdict(r) for r in rows]
                                 for key, rows in analysis_results.items()}}, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'dashboard_data.json').write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding='utf-8')
    if publish:
        publish_dashboard(dashboard)
    print(f"生产运行 {run_id} 完成；{dashboard['record_count']} 条已核验历史；未核验旧记录 {dashboard['excluded_records']['unverified']} 条")
    return dashboard


def generate_sample_history(days: int = 30, real_prices: Dict[str, float] = None):
    """生成模拟历史数据（用于展示前端曲线效果；source=mock 标记，回测会忽略）

    - 覆盖全部 12 个板块
    - 固定随机种子，模拟曲线跨运行保持稳定
    - 若提供 real_prices，模拟价格围绕今日真实价格小幅波动
    """
    import random
    import math
    from datetime import timedelta

    random.seed(42)
    real_prices = real_prices or {}
    
    history = {"records": []}
    base_indices = {
        "nasdaq": 30, "gold": 32, "telecom": 26, "semiconductor": 28,
        "innovative_drug": 26, "nonferrous_metals": 22, "new_energy": 22,
        "power": 18, "chip": 22, "robot": 20, "petrochemical": 18, "aerospace": 16,
    }
    fallback_price = 1.2  # 无真实价格时的默认基准

    today = datetime.now()
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        record = {"date": d.strftime("%Y-%m-%d"), "source": "mock", "sectors": {}}
        
        for sector, base in base_indices.items():
            # 模拟波动：当前趋势 + 随机噪音
            trend = 15 * math.sin(i / 10.0)  # 周期性波动
            noise = random.uniform(-8, 8)
            idx = round(base + trend + noise, 1)
            idx = max(0, min(100, idx))

            base_price = real_prices.get(sector, fallback_price)
            price = round(base_price * (1 + random.uniform(-0.03, 0.03)), 3)
            
            record["sectors"][sector] = {
                "index": idx,
                "price": price,
                "interpretation": interpret(idx),
                "details": {
                    "total_posts": random.randint(60, 85),
                    "valid_posts": random.randint(55, 80),
                    "spam_posts": random.randint(0, 5),
                    "newbie_posts": random.randint(3, 25),
                    "pure_newbie": random.randint(0, 5),
                    "newbie_ratio": round(random.uniform(5, 35), 1),
                    "avg_newbie_score": round(random.uniform(20, 50), 1),
                    "avg_sentiment": round(random.uniform(20, 80), 1),
                    "purity_signal": round(random.uniform(10, 60), 1),
                    "activity": round(random.uniform(60, 100), 1),
                },
                "top_newbie_posts": [],
            }
        
        history["records"].append(record)
    
    history["records"].sort(key=lambda r: r["date"])
    return history


def interpret(idx):
    if idx >= 75: return "🔴 极度狂热"
    if idx >= 60: return "🟠 高度警惕"
    if idx >= 40: return "🟡 开始升温"
    if idx >= 20: return "🟢 正常区间"
    return "🔵 极度冷清"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="宝妈指数生产采集或隔离演示数据")
    parser.add_argument('--demo', action='store_true', help='只生成 demo/history.json，不采集、不更新生产看板')
    args = parser.parse_args()
    if args.demo:
        target = Path(DATA_DIR) / 'demo'
        target.mkdir(parents=True, exist_ok=True)
        (target / 'history.json').write_text(json.dumps(generate_sample_history(), ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'演示历史已保存到 {target}，未修改生产数据')
    else:
        run_pipeline()
