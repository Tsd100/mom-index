"""
东方财富股吧采集器 — 反检测升级版
支持板块: 纳斯达克ETF, 黄金ETF, 通信ETF(CPO), 半导体ETF
"""
import re
import html as html_mod
import os
import requests
import time
from datetime import datetime
from typing import List, Dict, Optional

from .anti_detection import get_anti_detection

SECTORS = {
    "nasdaq":     {"name": "纳斯达克",  "code": "of159941", "etf": "513100"},
    "gold":       {"name": "黄金",      "code": "of518880", "etf": "518880"},
    "telecom":    {"name": "通信",      "code": "of515880", "etf": "515880"},
    "semiconductor": {"name": "半导体", "code": "of512480", "etf": "512480"},
    "innovative_drug":   {"name": "创新药",   "code": "of159992", "etf": "159992"},
    "nonferrous_metals": {"name": "有色金属", "code": "of512400", "etf": "512400"},
    "new_energy":        {"name": "新能源",   "code": "of516160", "etf": "516160"},
    "power":             {"name": "电力",     "code": "of159611", "etf": "159611"},
    "chip":              {"name": "芯片",     "code": "of159995", "etf": "159995"},
    "robot":             {"name": "机器人",   "code": "of562500", "etf": "562500"},
    "petrochemical":     {"name": "石油石化", "code": "of159930", "etf": "159930"},
    "aerospace":         {"name": "商业航天", "code": "of512710", "etf": "512710"},
}

PROXY = None

_ad = get_anti_detection()

# 每个板块抓取页数（可环境变量覆盖）
MAX_PAGES = int(os.environ.get("GUBA_PAGES", "3"))


def fetch_board(code: str, page: int = 1) -> str:
    """获取股吧页面HTML — 使用反检测请求头"""
    if page <= 1:
        url = f"https://guba.eastmoney.com/list,{code}.html"
    else:
        url = f"https://guba.eastmoney.com/list,{code},f_{page}.html"
    headers = _ad.get_common_headers(referer="https://guba.eastmoney.com")
    resp = requests.get(url, headers=headers, proxies=PROXY, timeout=15)
    resp.encoding = 'utf-8'
    return resp.text


def parse_posts(html_content: str) -> List[Dict]:
    """解析帖子列表"""
    title_pattern = re.compile(
        r'<a[^>]*href="(/news,[^"]*)"[^>]*title="([^"]*)"[^>]*>',
        re.DOTALL
    )
    read_pattern = re.compile(r'<cite[^>]*class="[^"]*l1[^"]*"[^>]*>(.*?)</cite>', re.DOTALL)
    reply_pattern = re.compile(r'<cite[^>]*class="[^"]*l2[^"]*"[^>]*>(.*?)</cite>', re.DOTALL)
    author_pattern = re.compile(r'<cite[^>]*class="[^"]*l4[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>', re.DOTALL)
    date_pattern = re.compile(r'<cite[^>]*class="[^"]*l5[^"]*"[^>]*>(.*?)</cite>', re.DOTALL)

    titles = title_pattern.findall(html_content)
    reads = read_pattern.findall(html_content)
    replies = reply_pattern.findall(html_content)
    authors = author_pattern.findall(html_content)
    dates = date_pattern.findall(html_content)

    posts = []
    for i, (url, title) in enumerate(titles):
        title = html_mod.unescape(title.strip())
        if not title or title == '点击开始搜索':
            continue
        posts.append({
            "id": f"guba_{url.split(',')[-1].replace('.html','')}",
            "title": title,
            "url": f"https://guba.eastmoney.com{url}",
            "platform": "guba",
            "author": authors[i].strip() if i < len(authors) else "未知",
            "reads": reads[i].strip() if i < len(reads) else "0",
            "replies": replies[i].strip() if i < len(replies) else "0",
            "date": dates[i].strip() if i < len(dates) else "未知",
            "collected_at": datetime.now().isoformat(),
        })
    return posts


def collect_all(pages: int = None) -> Dict[str, List[Dict]]:
    """采集所有板块 — 翻多页 + 按帖子ID去重，带人类延迟防触发风控

    低活跃板块首页帖子几天不变，翻页后样本更充分、指数更有区分度。
    某页没有新帖时提前结束，避免无谓请求。
    """
    pages = pages or MAX_PAGES
    result = {}
    for sector_key, cfg in SECTORS.items():
        seen = set()
        posts = []
        try:
            for page in range(1, pages + 1):
                html = fetch_board(cfg["code"], page)
                parsed = parse_posts(html)
                new_count = 0
                for p in parsed:
                    key = p.get("id") or p.get("url") or p.get("title")
                    if key not in seen:
                        seen.add(key)
                        posts.append(p)
                        new_count += 1
                print(f"  [{cfg['name']}] 第{page}页 解析{len(parsed)}条 新增{new_count}条")
                if new_count == 0:
                    break
                # 翻页之间加延迟
                _ad.sleep_like_human("scroll")
            result[sector_key] = posts
            print(f"  [{cfg['name']}] 合计 {len(posts)} 条（去重后）")
        except Exception as e:
            print(f"  [{cfg['name']}] 采集失败: {e}")
            result[sector_key] = posts
        # 板块之间加延迟
        _ad.sleep_like_human("scroll")
    return result


if __name__ == "__main__":
    data = collect_all()
    for k, v in data.items():
        print(f"{k}: {len(v)} posts")
