"""真实历史价格回填 — 腾讯K线接口

拉取过去 N 天各 ETF 的真实日K收盘价，写入 src/data/price_backfill.json。
前端价格曲线优先使用真实价格（含回填），情绪（指数）曲线仍以真实记录为准。

用法:
    python -m mom_index.backfill_history            # 默认 30 天
    python -m mom_index.backfill_history --days 60
"""
import argparse
import json
import os
import time

import requests

from mom_index.collectors.guba_collector import SECTORS

DATA_DIR = os.environ.get(
    "MOM_INDEX_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"),
)


def get_market_prefix(code: str) -> str:
    if code.startswith(("5", "6")):
        return "sh"
    if code.startswith(("8", "9")):
        return "bj"
    return "sz"


def fetch_kline(etf: str, days: int) -> list:
    """腾讯前复权日K: 返回 [{date, price(收盘)}]"""
    prefix = get_market_prefix(etf)
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
        f"param={prefix}{etf},day,,,{days},qfq"
    )
    resp = requests.get(url, timeout=15)
    node = resp.json()["data"][f"{prefix}{etf}"]
    kline = node.get("qfqday") or node.get("day") or []
    # 行格式: [date, open, close, high, low, volume]
    return [{"date": row[0], "price": float(row[2])} for row in kline]


def main(days: int = 180):
    """兼容旧命令，写入带标的证明的新行情格式，旧回填原件保持不变。"""
    from mom_index.market_data import fetch_market
    print('旧价格回填命令已切换为带标的与复权证明的 market_history.json')
    return fetch_market(DATA_DIR, days)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="真实历史价格回填")
    parser.add_argument("--days", type=int, default=int(os.environ.get("BACKFILL_DAYS", "180")))
    args = parser.parse_args()
    if not 10 <= args.days <= 1000:
        parser.error('--days 需在 10 到 1000 之间')
    main(days=args.days)
