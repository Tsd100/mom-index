"""每日情绪观察清单

把「指数绝对值 + 较前日变化 + 买卖比 + 价格趋势」合成一条可读结论，
让看板直接告诉用户该看什么，而不是丢 12 个数字自己解读。

经验分档只描述样本特征，阈值与预测能力尚未验证。
"""
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Dict, List

from mom_index.analyzer.index_calculator import SECTOR_NAMES
from mom_index.provenance import SHANGHAI, record_expired
from mom_index.daily_summary import comparable_previous

# 信号优先级（用于排序展示）
_ORDER = {"danger": 0, "warning": 1, "watch": 2, "normal": 3, "cold": 4, "unavailable": 5}
PRICE_WINDOW_BARS = 6
MAX_PRICE_AGE_DAYS = 3
MAX_PRICE_WINDOW_DAYS = 10


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
    """根据最新看板数据生成情绪观察清单。"""
    latest = dashboard.get("latest") or {}
    sectors = latest.get("sectors") or {}
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
        previous = comparable_previous(dashboard, key, s)
        comparable = previous is not None
        delta = idx - previous['index'] if comparable else None
        d = s.get("details") or {}
        ratio = d.get("buy_sell_ratio") or 0

        # 价格趋势必须使用当前映射标的，并且报价日期要贴近这次采集。
        price_trend = _confirmed_price_trend(dashboard, key, s, latest.get('date'))

        # 基础结论（按情绪区间）
        if idx >= 75:
            level, action = "danger", "🔴 讨论特征评分极高，请核对样本"
        elif idx >= 60:
            level, action = "warning", "🟠 讨论特征评分较高"
        elif idx >= 40:
            level, action = "watch", "🟡 讨论特征评分中等"
        elif idx >= 20:
            level, action = "normal", "🟢 讨论特征评分较低"
        else:
            level, action = "cold", "🔵 讨论特征评分很低"

        # 补充条件
        extras = [] if comparable else ["无可比上期记录或采集口径已变化"]
        if delta is not None:
            extras.append(f"较上次可比日 {previous['date']} {delta:+.1f}")
        if ratio >= 3 and idx >= 40:
            extras.append("样本中买入表达较多（不代表实际成交）")
        elif 0 < ratio <= 0.5 and idx >= 40:
            extras.append("样本中卖出表达较多（不代表实际成交）")
        if price_trend is not None and price_trend >= 0.05 and idx >= 40:
            extras.append("价格近 5 日上涨")
        if price_trend is not None and price_trend <= -0.05 and idx < 20:
            extras.append("价格近 5 日下跌，讨论特征评分较低")

        signals.append({
            "sector": key,
            "name": SECTOR_NAMES.get(key, key),
            "index": round(idx, 1),
            "delta": round(delta, 1) if delta is not None else None,
            "comparison_date": previous['date'] if comparable else None,
            "observation_version": 1,
            "level": level,
            "action": action,
            "extras": "；".join(extras),
        })

    signals.sort(key=lambda s: (_ORDER.get(s["level"], 9), -(s["index"] or 0)))
    return signals
