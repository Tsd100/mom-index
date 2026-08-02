"""宝妈指数回测 — 验证"高指数之后板块是否走弱"的反向指标假设

用法:
    python -m mom_index.backtest                  # 只看真实数据
    python -m mom_index.backtest --include-mock   # 连同模拟数据看（仅测试逻辑）
    python -m mom_index.backtest --horizons 5 10 20

输出:
    - 控制台表格：各情绪区间之后的 N 日平均收益
    - <数据目录>/backtest_report.md（Markdown 报告）

注意: 模拟历史（source=mock）默认被排除，避免用假数据得出假结论。
"""
import argparse
import json
import math
import os
import statistics
from datetime import datetime

DATA_DIR = os.environ.get(
    "MOM_INDEX_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"),
)

BANDS = [
    (0, 20, "🔵 极度冷清"),
    (20, 40, "🟢 正常区间"),
    (40, 60, "🟡 开始升温"),
    (60, 75, "🟠 高度警惕"),
    (75, 101, "🔴 极度狂热"),
]


def load_history(include_mock: bool = False):
    path = os.path.join(DATA_DIR, "history.json")
    if not os.path.exists(path):
        print(f"错误: 找不到历史数据 {path}，请先运行 python -m mom_index.pipeline")
        return []
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f).get("records", [])
    if not include_mock:
        records = [r for r in records if r.get("source") == "real"]
    return records


def build_price_series(records):
    """每个板块: 按日期排序的 (date, price) 序列"""
    series = {}
    for r in records:
        date = r["date"]
        for sector, data in (r.get("sectors") or {}).items():
            price = data.get("price")
            if price is None:
                continue
            series.setdefault(sector, []).append((date, price))
    for sector in series:
        dedup = {}
        for date, price in series[sector]:
            dedup[date] = price  # 同一天多条时保留最后一条
        series[sector] = sorted(dedup.items())
    return series


def forward_return(prices, date, horizon):
    """从 date 起第 horizon 个交易日后的收益率（数据不足返回 None）"""
    dates = [d for d, _ in prices]
    if date not in dates:
        return None
    i = dates.index(date)
    j = i + horizon
    if j >= len(prices) or not prices[i][1]:
        return None
    return (prices[j][1] - prices[i][1]) / prices[i][1]


def band_of(idx):
    for lo, hi, label in BANDS:
        if lo <= idx < hi:
            return label
    return "未知"


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def run(horizons=(5, 10, 20), include_mock=False):
    records = load_history(include_mock)
    if not records:
        print("暂无可用记录。"
              + ("（可加 --include-mock 查看模拟数据下的逻辑演示）" if not include_mock else ""))
        return

    prices = build_price_series(records)

    # 汇总每个 (板块, 日期) 的指数与各周期前瞻收益
    samples = []  # (sector, date, index, {horizon: return})
    for r in records:
        date = r["date"]
        for sector, data in (r.get("sectors") or {}).items():
            idx = data.get("index")
            if idx is None or sector not in prices:
                continue
            rets = {h: forward_return(prices[sector], date, h) for h in horizons}
            if any(v is not None for v in rets.values()):
                samples.append((sector, date, idx, rets))

    mode = "含模拟数据" if include_mock else "仅真实数据"
    if not samples:
        print(f"[{mode}] 没有可回测的样本：真实记录需要至少 2 个交易日才能计算前瞻收益。"
              "等 NAS 定时采集攒够数据后会自动生效。")
        report_path = os.path.join(DATA_DIR, "backtest_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(
                f"# 宝妈指数回测报告\n\n"
                f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"- 数据模式: {mode}\n\n"
                f"暂无足够样本：需要至少 2 个交易日才能计算前瞻收益。\n"
                f"等 NAS 定时采集积累真实记录后，回测会自动生效。\n"
            )
        print(f"📄 报告已保存: {report_path}")
        return

    print("=" * 74)
    print(f"   📈 宝妈指数回测报告（{mode}）")
    print(f"   {len(samples)} 个样本 · {len(prices)} 个板块 · "
          f"观察周期 {', '.join(str(h) for h in horizons)} 个交易日")
    print("=" * 74)

    rows = []
    for lo, hi, label in BANDS:
        group = [s for s in samples if lo <= s[2] < hi]
        if not group:
            continue
        line = [label, str(len(group))]
        for h in horizons:
            rets = [s[3][h] for s in group if s[3].get(h) is not None]
            line.append(f"{statistics.mean(rets) * 100:+.2f}%" if rets else "—")
        rows.append(line)

    print(f"\n{'区间':<12}{'样本':>6}  " + "  ".join(f"{h}日收益" for h in horizons))
    print("-" * 74)
    for row in rows:
        print(f"{row[0]:<12}{row[1]:>6}  " + "  ".join(f"{v:>10}" for v in row[2:]))

    # 相关性: 指数越高 → 未来收益越低（反指应表现为负相关）
    corr_lines = []
    for h in horizons:
        xs = [s[2] for s in samples if s[3].get(h) is not None]
        ys = [s[3][h] for s in samples if s[3].get(h) is not None]
        c = pearson(xs, ys)
        if c is not None:
            verdict = "负相关 ✅ 符合反向指标假设" if c < 0 else "非负 ⚠️ 反向假设暂未体现"
            corr_lines.append(f"    {h}日: 相关系数 = {c:+.3f}（{verdict}）")
    if corr_lines:
        print("\n📐 相关性检验（指数 vs 未来收益）:")
        for line in corr_lines:
            print(line)

    # 生成 Markdown 报告
    report_path = os.path.join(DATA_DIR, "backtest_report.md")
    lines = [
        "# 宝妈指数回测报告",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 数据模式: {mode}",
        f"- 样本数: {len(samples)}，板块数: {len(prices)}",
        f"- 观察周期: {', '.join(str(h) for h in horizons)} 个交易日",
        "",
        "## 各情绪区间之后的平均收益",
        "",
        "| 区间 | 样本 | " + " | ".join(f"{h}日收益" for h in horizons) + " |",
        "|------|------|" + "------|" * len(horizons),
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    if corr_lines:
        lines += ["", "## 相关性检验", ""]
        for line in corr_lines:
            lines.append(line.replace("    ", "- "))
    lines += [
        "",
        "> 说明: 回测仅用真实记录（source=real）。模拟历史用于前端预览，不参与结论。",
        "> 数据积累越多，结论越可靠；当前样本少时请勿据此操作。",
    ]
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n📄 报告已保存: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="宝妈指数回测")
    parser.add_argument("--include-mock", action="store_true",
                        help="连同模拟数据一起回测（仅测试逻辑用）")
    parser.add_argument("--horizons", nargs="+", type=int, default=[5, 10, 20],
                        help="观察周期（交易日），默认 5 10 20")
    args = parser.parse_args()
    run(horizons=tuple(args.horizons), include_mock=args.include_mock)
