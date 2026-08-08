"""
宝妈指数 — 主流程
采集 → 分析 → 计算 → 存储 → 输出
"""
import os
import json
from datetime import datetime
from typing import Dict

from mom_index.collectors.guba_collector import collect_all as collect_guba, SECTORS
from mom_index.collectors.xhs_collector import collect_all as collect_xhs
from mom_index.collectors.xueqiu_collector import collect_all as collect_xueqiu
from mom_index.analyzer.llm_analyzer import analyze_all
from mom_index.analyzer.signal import generate_signals
from mom_index.analyzer.index_calculator import (
    compute_sector_index, add_record, get_dashboard_data, save_history, load_history, SECTOR_NAMES
)
from mom_index.collectors.price_collector import fetch_all_prices
from mom_index.storage import save_posts, count_posts

DATA_DIR = os.environ.get("MOM_INDEX_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))


def run_pipeline():
    """执行完整的数据采集→分析→指数计算流程"""
    print("=" * 65)
    print("   👩‍👧 宝妈指数 · 数据采集与分析")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)
    
    # ===== 第1步: 数据采集 =====
    print("\n📡 第1步: 数据采集")
    
    all_posts = {}
    
    # 东方财富股吧
    print("  [东方财富股吧]")
    guba_data = collect_guba()
    for sector, posts in guba_data.items():
        all_posts[sector] = all_posts.get(sector, []) + posts
        saved = save_posts(sector, posts, platform="guba")
        if saved:
            print(f"    ↳ 已存档 {saved} 条原始帖子")
    
    # 小红书 (如果有API Key)
    print("  [小红书]")
    try:
        xhs_data = collect_xhs()
        for sector, posts in xhs_data.items():
            all_posts[sector] = all_posts.get(sector, []) + posts
            saved = save_posts(sector, posts, platform="xhs")
            if saved:
                print(f"    ↳ 已存档 {saved} 条原始帖子")
    except Exception as e:
        print(f"  小红书采集跳过: {e}")

    # 雪球（可选，需 MOM_INDEX_ENABLE_XUEQIU=1 + 登录 Cookie）
    print("  [雪球]")
    try:
        xueqiu_data = collect_xueqiu()
        for sector, posts in xueqiu_data.items():
            all_posts[sector] = all_posts.get(sector, []) + posts
            saved = save_posts(sector, posts, platform="xueqiu")
            if saved:
                print(f"    ↳ 已存档 {saved} 条原始帖子")
    except Exception as e:
        print(f"  雪球采集跳过: {e}")
    
    total_collected = sum(len(v) for v in all_posts.values())
    print(f"\n  共采集 {total_collected} 条帖子（累计存档 {count_posts()} 条）\n")
    
    # ===== 第2步: LLM分析 =====
    print("🧠 第2步: LLM 多维度分析")
    analysis_results = analyze_all(all_posts)
    
    # 打印每个板块的 top 小白帖
    for sector, results in analysis_results.items():
        top_newbie = [r for r in results if r.newbie_score >= 30][:3]
        print(f"\n  [{SECTOR_NAMES.get(sector, sector)}] 共分析 {len(results)} 条")
        if top_newbie:
            print(f"  🔥 典型小白帖:")
            for r in top_newbie:
                print(f"     [{r.level} {r.newbie_score}分] {r.title[:50]}...")
    
    # ===== 第3步: 指数计算 =====
    print("\n📊 第3步: 指数计算")
    
    sector_indices = {}
    for sector, results in analysis_results.items():
        result = compute_sector_index(results)
        sector_indices[sector] = result
        name = SECTOR_NAMES.get(sector, sector)
        d = result["details"]
        bar = "█" * int(result["index"] / 5) + "░" * (20 - int(result["index"] / 5))
        print(f"  {name:6s} {bar} {result['index']:5.1f}  [{d.get('newbie_posts', 0)}/{d.get('total_posts', 0)}小白, {d.get('newbie_ratio', 0)}%]")
    
    # ===== 第4步: 存储历史 =====
    # ===== 价格采集 =====
    print("\n💰 价格采集")
    prices = fetch_all_prices(SECTORS)
    
    # ===== 第4步: 存储历史 =====
    print("\n💾 第4步: 存储历史记录")
    add_record(sector_indices, analysis_results, prices)
    
    # ===== 第5步: 输出前端数据 =====
    dashboard = get_dashboard_data()

    # 真实数据不足时，补充稳定的模拟历史（仅用于前端曲线预览；source=mock 会被回测忽略）
    real_count = dashboard.get("real_record_count", dashboard["record_count"])
    if real_count < 5:
        latest = dashboard.get("latest") or {}
        real_prices = {
            k: v.get("price")
            for k, v in (latest.get("sectors") or {}).items()
            if v.get("price") is not None
        }
        sample = generate_sample_history(30, real_prices)
        real_dates = set(dashboard.get("real_dates", []))
        merged = {"records": []}
        for rec in sample["records"]:
            if rec["date"] not in real_dates:
                merged["records"].append(rec)
        history = load_history()
        merged["records"].extend(
            r for r in history["records"] if r.get("source") == "real"
        )
        merged["records"].sort(key=lambda r: r["date"])
        save_history(merged)
        dashboard = get_dashboard_data()  # 重新读取（含模拟历史）
        print(f"\n📝 已补充 30 天模拟历史用于前端展示（真实记录 {real_count} 条）")
    else:
        # 真实记录已充足：清除模拟历史，只保留真实记录
        history = load_history()
        real_records = [r for r in history["records"] if r.get("source") == "real"]
        if len(real_records) != len(history["records"]):
            save_history({"records": real_records})
            dashboard = get_dashboard_data()
            print(f"\n✅ 真实记录已满 {real_count} 天，已移除模拟历史")

    # 生成每日操作信号清单
    dashboard["signals"] = generate_signals(dashboard)

    os.makedirs(DATA_DIR, exist_ok=True)
    dashboard_file = os.path.join(DATA_DIR, "dashboard_data.json")
    with open(dashboard_file, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)
    print(f"  数据已保存: {dashboard_file}")
    
    # 同步到 frontend/data/（前端服务器从这里读取）
    frontend_data_dir = os.path.join(os.path.dirname(__file__), "frontend", "data")
    os.makedirs(frontend_data_dir, exist_ok=True)
    for fname in ["dashboard_data.json", "history.json", "xhs_posts.json"]:
        src = os.path.join(DATA_DIR, fname)
        dst = os.path.join(frontend_data_dir, fname)
        if os.path.exists(src):
            import shutil
            shutil.copy2(src, dst)
    print(f"  已同步到: {frontend_data_dir}")
    
    # ===== 总结 =====
    print("\n" + "=" * 65)
    print("   ✅ 分析完成!")
    print(f"   历史记录: {dashboard['record_count']} 条")
    if dashboard["latest"]:
        for sector, data in dashboard["latest"]["sectors"].items():
            name = SECTOR_NAMES.get(sector, sector)
            print(f"   {name}: {data['index']} — {data['interpretation']}")
    print("=" * 65)

    # 信号清单摘要
    if dashboard.get("signals"):
        print("\n🚦 今日操作信号:")
        for s in dashboard["signals"][:5]:
            extra = f"（{s['extras']}）" if s["extras"] else ""
            print(f"   {s['name']:6s} {s['index']:5.1f}  {s['action']}{extra}")
    
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
    # 先跑真实采集
    dashboard = run_pipeline()
    print(f"\n📊 看板数据已就绪: {dashboard['record_count']} 条历史记录"
          f"（真实 {dashboard.get('real_record_count', 0)} 条）")
