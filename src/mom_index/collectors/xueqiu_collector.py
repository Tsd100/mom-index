"""雪球数据采集器（替代数据源候选）

现状（2026-08 实测）:
  - 网页搜索接口被阿里云 WAF 拦截（返回 JS 挑战页）
  - api.xueqiu.com / stock.xueqiu.com 接口返回 400016，要求登录 token（xq_a_token）

因此纯 requests 模式无法稳定工作，默认关闭（MOM_INDEX_ENABLE_XUEQIU=1 才尝试）。
接入真实数据需要二选一：
  1. 配置有效登录 Cookie（XUEQIU_COOKIE），保持会话
  2. 用 Playwright + 已登录浏览器会话（预留接口）
微博/抖音同理需要登录态与反爬，暂未实现。
"""
import os
from typing import Dict, List

import requests

ENABLED = os.environ.get("MOM_INDEX_ENABLE_XUEQIU") == "1"
COOKIE = os.environ.get("XUEQIU_COOKIE", "")

SEARCH_KEYWORDS = {
    "nasdaq": ["纳指 还能买吗", "纳斯达克 新手"],
    "gold": ["黄金 还能涨吗", "黄金 亏了"],
    "telecom": ["CPO 光模块", "通信ETF"],
    "semiconductor": ["半导体 还能买吗", "芯片 新手"],
}


def _search(keyword: str, count: int = 10) -> List[Dict]:
    """雪球帖子搜索（需要登录态，否则被 WAF/400016 拦截）"""
    url = "https://xueqiu.com/query/v1/search/status.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": "https://xueqiu.com/",
    }
    cookies = {}
    if COOKIE:
        for item in COOKIE.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                cookies[k] = v
    resp = requests.get(url, params={"q": keyword, "count": count, "page": 1},
                        headers=headers, cookies=cookies, timeout=15)
    data = resp.json()  # 无登录态时这里会抛异常（返回 WAF HTML/400016）
    return [
        {
            "id": f"xq_{s.get('id', '')}",
            "title": s.get("title", "").strip(),
            "url": f"https://xueqiu.com/{s.get('user_id', '')}/{s.get('id', '')}",
            "platform": "xueqiu",
            "author": (s.get("user") or {}).get("screen_name", ""),
            "date": str(s.get("created_at", "")),
            "collected_at": __import__("datetime").datetime.now().isoformat(),
        }
        for s in (data.get("list") or [])
        if s.get("title")
    ]


def collect_all() -> Dict[str, List[Dict]]:
    """采集所有板块（需 MOM_INDEX_ENABLE_XUEQIU=1 + 有效登录 Cookie）"""
    if not ENABLED:
        print("  ⚠️ 雪球未启用（设置 MOM_INDEX_ENABLE_XUEQIU=1 开启）")
        return {}
    if not COOKIE:
        print("  ⚠️ 雪球需要登录 Cookie（XUEQIU_COOKIE），当前无法采集")
        return {}
    result = {}
    for sector, keywords in SEARCH_KEYWORDS.items():
        posts = []
        for kw in keywords:
            try:
                posts.extend(_search(kw))
            except Exception as e:
                print(f"  [雪球-{sector}] 搜索「{kw}」失败: {e}")
        result[sector] = posts
        print(f"  [雪球-{sector}] {len(posts)} 条")
    return result


if __name__ == "__main__":
    for k, v in collect_all().items():
        print(f"{k}: {len(v)} posts")
