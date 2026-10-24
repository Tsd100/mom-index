"""每日操作信号清单

把「指数绝对值 + 较前日变化 + 买卖比 + 价格趋势」合成一条可读结论，
让看板直接告诉用户该看什么，而不是丢 12 个数字自己解读。

注意: 这是经验规则，不是投资建议；阈值会随回测数据积累而校准。
"""
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Dict, List

from mom_index.analyzer.index_calculator import SECTOR_NAMES
from mom_index.provenance import SHANGHAI, record_expired

# 信号优先级（用于排序展示）
_ORDER = {"danger": 0, "warning": 1, "watch": 2, "normal": 3, "cold": 4, "unavailable": 5}
PRICE_WINDOW_BARS = 6
MAX_PRICE_AGE_DAYS = 3
MAX_PRICE_WINDOW_DAYS = 10


def _prev_real_index(sector_history: List[Dict], real_dates) -> float | None:
    """该板块上一个真实交易日的指数（真实记录之间比较，排除模拟点）"""
    pts = sorted(
        (r["date"], r["index"]) for r in sector_history if r["date"] in real_dates and r.get("index") is not None
    )
    if len(pts) < 2:
        return None
    return pts[-2][1]


def _confirmed_price_trend(dashboard: Dict, sector: str, sector_data: Dict, signal_date: str):
    """只在同一 ETF 且行情日期紧邻采集日时给出价格趋势。"""
    current = (dashboard.get('instruments') or {}).get(sector) or {}
    captured = sector_data.get('instrument') or {}
    current_etf = current.get('etf')
    if (not current_etf or captured.get('etf') != current_etf
            or sector_data.get('mapping_warning')):
        return None
    try:
        as_of = date.fromisoformat(signal_date)
        finished_at = datetime.fromisoformat(
            str((dashboard.get('latest') or {}).get('provenance', {}).get('finished_at', ''))
        )
    except (TypeError, ValueError):
        return None
    if finished_at.tzinfo is None:
        return None
    finished_local = finished_at.astimezone(SHANGHAI)
    if finished_local.date() != as_of:
        return None
    close_is_complete = (finished_local.hour, finished_local.minute, finished_local.second) >= (15, 15, 0)
    latest_completed_day = as_of if close_is_complete else as_of - timedelta(days=1)

    by_date = {}
    for row in (dashboard.get('price_history') or {}).get(sector, []):
        try:
            day = date.fromisoformat(str(row.get('date', '')))
            price = float(row.get('price'))
        except (TypeError, ValueError):
            continue
        if day > latest_completed_day or price <= 0 or not isfinite(price):
            continue
        if row.get('etf') and row['etf'] != current_etf:
            continue
        by_date[day] = price

    bars = sorted(by_date.items())
    if len(bars) < PRICE_WINDOW_BARS:
        return None
    window = bars[-PRICE_WINDOW_BARS:]
    if ((as_of - window[-1][0]).days > MAX_PRICE_AGE_DAYS
            or (as_of - window[0][0]).days > MAX_PRICE_WINDOW_DAYS):
        return None
    return (window[-1][1] - window[0][1]) / window[0][1]


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

        # 价格趋势必须使用当前映射标的，并且报价日期要贴近这次采集。
        price_trend = _confirmed_price_trend(dashboard, key, s, latest.get('date'))

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
        if price_trend is not None and price_trend >= 0.05 and idx >= 40:
            extras.append("价格近 5 日上涨")
        if price_trend is not None and price_trend <= -0.05 and idx < 20:
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
