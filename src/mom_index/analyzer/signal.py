"""每日操作信号清单

把「指数绝对值 + 较前日变化 + 买卖比 + 价格趋势」合成一条可读结论，
让看板直接告诉用户该看什么，而不是丢 12 个数字自己解读。

注意: 这是经验规则，不是投资建议；阈值会随回测数据积累而校准。
"""
from typing import Dict, List

from mom_index.analyzer.index_calculator import SECTOR_NAMES
from mom_index.provenance import record_expired

# 信号优先级（用于排序展示）
_ORDER = {"danger": 0, "warning": 1, "watch": 2, "normal": 3, "cold": 4, "unavailable": 5}


def _prev_real_index(sector_history: List[Dict], real_dates) -> float | None:
    """该板块上一个真实交易日的指数（真实记录之间比较，排除模拟点）"""
    pts = sorted(
        (r["date"], r["index"]) for r in sector_history if r["date"] in real_dates and r.get("index") is not None
    )
    if len(pts) < 2:
        return None
    return pts[-2][1]


def generate_signals(dashboard: Dict) -> List[Dict]:
    """根据最新看板数据生成操作信号清单"""
    latest = dashboard.get("latest") or {}
    sectors = latest.get("sectors") or {}
    real_dates = set(dashboard.get("real_dates") or [])
    signals = []

    for key, s in sectors.items():
        quality = s.get("quality", {})
        if s.get("index") is None or quality.get("status") != "ok" or record_expired(latest):
            signals.append({"sector": key, "name": SECTOR_NAMES.get(key, key),
                            "index": s.get("index"), "delta": None, "level": "unavailable",
                            "action": "数据不足，暂停情绪判断",
                            "extras": '采集结果过期或时间未核验' if record_expired(latest) else "；".join(quality.get("reasons", ["样本质量未核验"]))})
            continue
        idx = s["index"]
        prev = _prev_real_index(dashboard.get("sector_history", {}).get(key, []), real_dates)
        points = sorted(dashboard.get("sector_history", {}).get(key, []), key=lambda p: p["date"])
        comparable = (len(points) >= 2 and points[-2].get("index") is not None
                      and points[-1].get("definition_id")
                      and points[-1].get("definition_id") == points[-2].get("definition_id"))
        delta = (idx - prev) if prev is not None and comparable else None
        d = s.get("details") or {}
        ratio = d.get("buy_sell_ratio") or 0

        # 价格趋势：最新收盘 vs 5 个交易日前（价格曲线含真实回填）
        ph = dashboard.get("price_history", {}).get(key, [])
        price_trend = 0.0
        if len(ph) >= 6:
            p0, p1 = ph[-1].get("price"), ph[-6].get("price")
            if p0 and p1:
                price_trend = (p0 - p1) / p1

        # 基础结论（按情绪区间）
        if idx >= 75:
            level, action = "danger", "🚨 历史级危险：小白极度狂热，避免追高"
        elif idx >= 60:
            level, action = "warning", "⚠️ 情绪过热：小白大量涌入，注意减仓风险"
        elif idx >= 40:
            level, action = "watch", "👀 升温中：小白活跃度上升，不追高、盯变化"
        elif idx >= 20:
            level, action = "normal", "✅ 正常区间：情绪平稳，维持原策略"
        else:
            level, action = "cold", "🧊 极度冷清：小白沉默，列入左侧观察池"

        # 补充条件
        extras = [] if comparable else ["无可比上期记录或采集口径已变化"]
        if delta is not None:
            extras.append(f"较前日 {delta:+.1f}")
        if ratio >= 3 and idx >= 40:
            extras.append("小白买盘一边倒（追涨情绪）")
        elif 0 < ratio <= 0.5 and idx >= 40:
            extras.append("小白恐慌卖盘占优")
        if price_trend >= 0.05 and idx >= 40:
            extras.append("价格近 5 日上涨")
        if price_trend <= -0.05 and idx < 20:
            extras.append("价格近 5 日下跌，情绪冰点")

        signals.append({
            "sector": key,
            "name": SECTOR_NAMES.get(key, key),
            "index": round(idx, 1),
            "delta": round(delta, 1) if delta is not None else None,
            "level": level,
            "action": action,
            "extras": "；".join(extras),
        })

    signals.sort(key=lambda s: (_ORDER.get(s["level"], 9), -(s["index"] or 0)))
    return signals
