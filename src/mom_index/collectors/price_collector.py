"""宝妈指数 — 行情价格采集器
使用腾讯财经 API 获取 ETF 实时价格（免费、不封IP）
"""
import requests
from typing import Dict, Optional


def get_market_prefix(code: str) -> str:
    """判断所属市场 sh/sz/bj"""
    if code.startswith(('5', '6')):
        return 'sh'
    elif code.startswith(('8', '9')):
        return 'bj'
    return 'sz'


def fetch_etf_price(etf_code: str) -> Optional[float]:
    """获取单个 ETF 实时价格"""
    prefix = get_market_prefix(etf_code)
    url = f"https://qt.gtimg.cn/q={prefix}{etf_code}"
    try:
        resp = requests.get(url, timeout=10)
        resp.encoding = 'gbk'
        text = resp.text.strip()
        if not text or '=' not in text:
            return None
        # v_sh513100="1~纳指ETF~513100~1.234~..."
        fields = text.split('=')[1].strip('"').split('~')
        return float(fields[3]) if len(fields) > 3 else None
    except Exception:
        return None


def fetch_all_prices(sectors: Dict) -> Dict[str, float]:
    """获取所有板块的 ETF 实时价格"""
    prices = {}
    for key, cfg in sectors.items():
        etf = cfg.get("etf", "")
        if not etf:
            continue
        price = fetch_etf_price(etf)
        if price is not None:
            prices[key] = price
        else:
            print(f"  ⚠ [{cfg['name']}] 价格获取失败")
    return prices


if __name__ == "__main__":
    from guba_collector import SECTORS
    p = fetch_all_prices(SECTORS)
    for k, v in p.items():
        print(f"{k}: {v}")
