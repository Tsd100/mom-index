"""
宝妈指数计算引擎
四个板块独立计算，各自有完整的历史曲线
"""
from datetime import datetime, date
from typing import Dict, List
import json
import os
from copy import deepcopy
from mom_index.instruments import SECTORS, record_instrument
from mom_index.provenance import verified_record, now_local, SCHEMA_VERSION
from mom_index.sample_insights import COMPONENT_VERSION

DATA_DIR = os.environ.get("MOM_INDEX_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"))

SECTOR_NAMES = {
    "nasdaq": "纳斯达克",
    "gold": "黄金",
    "telecom": "通信",
    "semiconductor": "半导体",
    "innovative_drug": "创新药",
    "nonferrous_metals": "有色金属",
    "new_energy": "新能源",
    "power": "电力",
    "chip": "芯片",
    "robot": "机器人",
    "petrochemical": "石油石化",
    "aerospace": "商业航天",
}


def compute_sector_index(analysis_results: List) -> Dict:
    """
    计算单个板块的宝妈指数 (0-100)
    
    四个维度:
    1. 小白占比 (40%) — 该板块中小白帖的比例
    2. 小白强度 (25%) — 小白帖的平均得分
    3. 情绪极端度 (20%) — 贪婪/恐慌的情绪极端程度
    4. 小白纯度 (15%) — 纯小白在小白帖中的占比（纯度越高，情绪越无脑）
    """
    if not analysis_results:
        return {
            "index": None,
            "interpretation": "无数据",
            "details": {}
        }
    
    total = len(analysis_results)
    
    # 过滤掉垃圾帖
    valid_posts = [r for r in analysis_results if r.level != "垃圾帖"]
    spam_count = total - len(valid_posts)
    
    # 小白帖（分数 >= 20）
    newbie_posts = [r for r in valid_posts if r.newbie_score >= 20]
    pure_newbie = [r for r in valid_posts if r.newbie_score >= 50]
    newbie_count = len(newbie_posts)
    
    # 维度1: 小白占比 (0-100) — 基于有效帖子
    newbie_ratio = (newbie_count / len(valid_posts)) * 100 if valid_posts else 0
    
    # 维度2: 小白强度 (0-100)
    avg_newbie_score = sum(r.newbie_score for r in newbie_posts) / max(newbie_count, 1)
    
    # 维度3: 情绪极端度 (0-100)
    sentiments = [abs(r.sentiment_score) for r in newbie_posts]
    avg_sentiment = sum(sentiments) / max(len(sentiments), 1) * 100
    
    # 维度4: 热度信号 (0-100) — 小白帖占比越高 + 纯小白越多 = 信号越强
    purity_signal = (len(pure_newbie) / max(newbie_count, 1)) * 100 if newbie_count > 0 else 0
    activity_signal = min(100, len(valid_posts) / 80 * 100)  # 80条为满热度
    
    # 综合指数
    index = (
        newbie_ratio * 0.40 +
        avg_newbie_score * 0.25 +
        avg_sentiment * 0.20 +
        purity_signal * 0.15
    )
    
    index = round(min(100, index), 1)
    
    # ---- 买入/卖出子指数 ----
    newbie_buy = [r for r in newbie_posts if r.intent == "buy"]
    newbie_sell = [r for r in newbie_posts if r.intent == "sell"]
    
    buy_ratio = len(newbie_buy) / max(newbie_count, 1)
    sell_ratio = len(newbie_sell) / max(newbie_count, 1)
    buy_intensity = sum(r.intent_strength for r in newbie_buy) / max(len(newbie_buy), 1)
    sell_intensity = sum(r.intent_strength for r in newbie_sell) / max(len(newbie_sell), 1)
    
    # 买入指数: 小白买入占比(50%) + 小白热度(30%) + 买入强度(20%)
    mom_buy_index = round(min(100, (
        buy_ratio * 100 * 0.50 +
        (avg_newbie_score / 100) * buy_ratio * 30 * 0.30 +
        buy_intensity * 100 * 0.20
    )), 1)
    
    # 卖出指数: 小白卖出占比(50%) + 小白热度(30%) + 卖出强度(20%)
    mom_sell_index = round(min(100, (
        sell_ratio * 100 * 0.50 +
        (avg_newbie_score / 100) * sell_ratio * 30 * 0.30 +
        sell_intensity * 100 * 0.20
    )), 1)
    
    # 买卖比: >1 表示买入情绪占优, <1 表示恐慌卖出占优
    buy_sell_ratio = round(len(newbie_buy) / max(len(newbie_sell), 1), 1)
    
    return {
        "index": index,
        "score_components": {'version':COMPONENT_VERSION, 'values':{
            'feature_share':newbie_ratio*0.40, 'feature_strength':avg_newbie_score*0.25,
            'emotion_extremity':avg_sentiment*0.20, 'feature_purity':purity_signal*0.15}},
        "interpretation": interpret_index(index),
        "details": {
            "total_posts": total,
            "valid_posts": len(valid_posts),
            "spam_posts": spam_count,
            "newbie_posts": newbie_count,
            "pure_newbie": len(pure_newbie),
            "newbie_ratio": round(newbie_ratio, 1),
            "avg_newbie_score": round(avg_newbie_score, 1),
            "avg_sentiment": round(avg_sentiment, 1),
            "purity_signal": round(purity_signal, 1),
            "activity": round(activity_signal, 1),
            # 买入/卖出子指数
            "mom_buy_index": mom_buy_index,
            "mom_sell_index": mom_sell_index,
            "buy_sell_ratio": buy_sell_ratio,
            "buy_count": len(newbie_buy),
            "sell_count": len(newbie_sell),
        },
        "top_newbie_posts": [
            {
                "title": r.title[:60],
                "source_url": r.source_url,
                "score": r.newbie_score,
                "level": r.level,
                "reasoning": r.reasoning[:150],
                "sentiment": r.sentiment_score,
                "intent": r.intent,
                "intent_label": {"buy": "🟢 买入表达", "sell": "🔴 卖出表达", "neutral": "⚪ 方向未确认"}.get(r.intent, ""),
                "intent_basis": r.intent_basis,
                "key_signals": r.key_signals[:2],
            }
            for r in sorted(newbie_posts, key=lambda x: x.newbie_score, reverse=True)[:5]
        ],
    }


def interpret_index(index: float) -> str:
    if index >= 75:
        return "🔴 讨论特征评分极高 — 请结合样本与原帖核查"
    elif index >= 60:
        return "🟠 讨论特征评分较高 — 不代表未来价格方向"
    elif index >= 40:
        return "🟡 讨论特征评分中等 — 变化需与同口径记录比较"
    elif index >= 20:
        return "🟢 讨论特征评分较低 — 分档尚未校准"
    else:
        return "🔵 讨论特征评分很低 — 分档尚未校准"


def load_history() -> Dict:
    """合并读取旧历史与独立生产历史；是否核验由消费者明确筛选。"""
    records = []
    for relative in ('history.json', 'production/history.json'):
        path = os.path.join(DATA_DIR, relative)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as handle:
                records.extend(json.load(handle).get('records', []))
    return {'records': sorted(records, key=lambda r: r['date'])}


def save_history(history: Dict, production=False):
    """原子保存。新生产记录与旧历史、演示历史分目录存放。"""
    directory = os.path.join(DATA_DIR, 'production') if production else DATA_DIR
    os.makedirs(directory, exist_ok=True)
    history_file = os.path.join(directory, 'history.json')
    temporary = history_file + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(history, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, history_file)


def add_record(sector_indices: Dict[str, Dict], analysis_results: Dict, prices: Dict[str, float] = None, provenance: Dict = None):
    """添加一条历史记录"""
    if prices:
        for sid, price in prices.items():
            if sid in sector_indices:
                sector_indices[sid]["price"] = price
    
    history = {"records": [r for r in load_history()["records"] if verified_record(r)]}
    
    record = {
        "date": now_local().strftime("%Y-%m-%d"),
        "timestamp": now_local().isoformat(),
        "provenance": provenance or {},
        "source": "real",
        "sectors": sector_indices,
    }
    
    # 如果今天已有记录，更新而非新增
    today = record["date"]
    existing = [r for r in history["records"] if r["date"] == today and verified_record(r)]
    if existing:
        history["records"] = [r for r in history["records"] if r["date"] != today or not verified_record(r)]
    
    history["records"].append(record)
    history["records"].sort(key=lambda r: r["date"])
    save_history(history, production=True)


def get_dashboard_data() -> Dict:
    """获取前端所需的完整数据"""
    history = load_history()
    all_records = history.get("records", [])
    records = sorted((r for r in all_records if verified_record(r)), key=lambda r: r["date"])
    excluded = {"mock": sum(r.get("source") == "mock" for r in all_records),
                "unverified": sum(r.get("source") != "mock" and not verified_record(r) for r in all_records)}
    
    # 最新一条
    latest = deepcopy(records[-1]) if records else None
    if latest:
        for sector, data in latest.get('sectors', {}).items():
            data['interpretation'] = (interpret_index(data['index'])
                                      if data.get('index') is not None and data.get('quality', {}).get('status') == 'ok'
                                      else '数据不足，暂停情绪判断')
            data['instrument'] = record_instrument(latest, sector) or {}
            original = latest['provenance']['definition'].get('sectors', {}).get(sector, {})
            if not data['instrument']:
                data['mapping_warning'] = f"原采集 {original.get('code', '未知')} 与价格 {original.get('etf', '未知')} 不一致"
            elif data['instrument'].get('etf') != SECTORS.get(sector, {}).get('etf'):
                data['mapping_warning'] = '最近采集仍为旧标的；新映射需重新采集后生效'

    # 真实记录统计（source == "real"；模拟记录用于前端预览，回测与后续分析会忽略）
    real_records = [r for r in records if r.get("source") == "real"]
    real_dates = sorted({r["date"] for r in real_records})
    
    # 为每个板块准备历史曲线数据
    sector_history = {key: [] for key in SECTOR_NAMES}
    price_history = {key: [] for key in SECTOR_NAMES}
    price_real_dates = set()
    
    for r in records:
        for sector, data in r.get("sectors", {}).items():
            if sector in sector_history:
                sector_history[sector].append({
                    "date": r["date"],
                    "index": data["index"] if data.get("quality", {}).get("status") == "ok" else None,
                    "definition_id": data.get("definition_id"),
                    "score_components": deepcopy(data.get('score_components')),
                })
            cfg = record_instrument(r, sector)
            if sector in price_history and "price" in data and cfg and cfg['etf'] == SECTORS[sector]['etf']:
                price_history[sector].append({
                    "date": r["date"],
                    "price": data["price"],
                })
                price_real_dates.add(r["date"])

    # 旧 price_backfill.json 没有标的/复权证明，不再用于新映射价格曲线。
    market_file = os.path.join(DATA_DIR, 'market_history.json')
    if os.path.exists(market_file):
        from mom_index.provenance import digest, SHANGHAI
        from mom_index.market_data import completed_rows
        with open(market_file, encoding='utf-8') as handle:
            market = json.load(handle)
        if market.get('dataset_id') == digest({k: v for k, v in market.items() if k != 'dataset_id'}):
            price_history = {key: [] for key in SECTOR_NAMES}
            price_real_dates = set()
            fetched = datetime.fromisoformat(market['fetched_at']).astimezone(SHANGHAI)
            for sector, cfg in SECTORS.items():
                node = market.get('instruments', {}).get(cfg['etf'], {})
                if node.get('rows_hash') != digest(node.get('rows', [])):
                    continue
                for row in completed_rows(node.get('rows', []), fetched):
                    price_history[sector].append({'date': row['date'], 'price': row['close'], 'etf': cfg['etf']})
                    price_real_dates.add(row['date'])

    dashboard = {
        "instruments": deepcopy(SECTORS),
        "schema_version": SCHEMA_VERSION,
        "mode": "production",
        "excluded_records": excluded,
        "latest": latest,
        "sector_history": sector_history,
        "price_history": price_history,
        "record_count": len(records),
        "real_record_count": len(real_records),
        "real_dates": real_dates,
        "price_real_dates": sorted(price_real_dates),
    }
    from mom_index.daily_summary import build_daily_summary
    dashboard['daily_summary'] = build_daily_summary(dashboard)
    from mom_index.sample_insights import quality_overview
    dashboard['quality_overview'] = quality_overview(records)
    return dashboard
