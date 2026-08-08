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


def main(days: int = 30):
    result = {}
    print(f"📈 拉取 {days} 天真实ETF日K收盘价...")
    for key, cfg in SECTORS.items():
        try:
            rows = fetch_kline(cfg["etf"], days)
            result[key] = rows
            span = f"{rows[0]['date']} ~ {rows[-1]['date']}" if rows else "空"
            print(f"  [{cfg['name']}] {len(rows)} 天 ({span})")
        except Exception as e:
            print(f"  [{cfg['name']}] 失败: {e}")
        time.sleep(0.5)

    out = os.path.join(DATA_DIR, "price_backfill.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已保存: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="真实历史价格回填")
    parser.add_argument("--days", type=int, default=int(os.environ.get("BACKFILL_DAYS", "30")))
    args = parser.parse_args()
    main(days=args.days)
