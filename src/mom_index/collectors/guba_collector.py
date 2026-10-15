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


class IdentityChallengeError(RuntimeError):
    """响应为身份核验页，不是可分析的股吧列表。"""


def fetch_board(code: str, page: int = 1) -> str:
    """获取股吧页面HTML — 使用反检测请求头"""
    if page <= 1:
        url = f"https://guba.eastmoney.com/list,{code}.html"
    else:
        url = f"https://guba.eastmoney.com/list,{code},f_{page}.html"
    headers = _ad.get_common_headers(referer="https://guba.eastmoney.com")
    resp = requests.get(url, headers=headers, proxies=PROXY, timeout=15)
    resp.raise_for_status()
    resp.encoding = 'utf-8'
    if re.search(r'<title>\s*身份核实\s*</title>', resp.text):
        raise IdentityChallengeError('数据源要求身份核实，暂停该来源采集')
    return resp.text


def parse_posts(html_content: str) -> List[Dict]:
    """按单条 articleh 行解析字段，支持 span/cite，避免跳过标题后字段错位。"""
    rows = re.findall(r'<div\b[^>]*class=[\"\'][^\"\']*\barticleh\b[^\"\']*[\"\'][^>]*>(.*?)</div>', html_content, re.S)
    posts = []
    for row in rows:
        match = re.search(r'<a[^>]*href="(/news,[^"]*)"[^>]*title="([^"]*)"[^>]*>', row, re.S)
        if not match:
            continue
        url, title = match.groups()
        title = html_mod.unescape(title.strip())
        if not title or title == '点击开始搜索':
            continue

        def field(name, fallback):
            value = re.search(r'<(?:span|cite)\b[^>]*class="[^\"]*\b' + name + r'\b[^\"]*"[^>]*>(.*?)</(?:span|cite)>', row, re.S)
            return html_mod.unescape(re.sub(r'<[^>]+>', '', value.group(1))).strip() if value else fallback

        updated = field('l5', '未知')
        posts.append({
            'id': f"guba_{url.split(',')[-1].replace('.html', '')}",
            'title': title, 'url': f'https://guba.eastmoney.com{url}',
            'platform': 'guba', 'source': 'real', 'author': field('l4', '未知'),
            'reads': field('l1', '0'), 'replies': field('l2', '0'),
            'date': updated, 'list_updated_at': updated,
            'collected_at': datetime.now().astimezone().isoformat(),
        })
    return posts


def collect_all(pages: int = None, report: Dict = None) -> Dict[str, List[Dict]]:
    """采集所有板块 — 翻多页 + 按帖子ID去重，带人类延迟防触发风控

    低活跃板块首页帖子几天不变，翻页后样本更充分、指数更有区分度。
    某页没有新帖时提前结束，避免无谓请求。
    """
    pages = pages or MAX_PAGES
    result = {}
    for sector_key, cfg in SECTORS.items():
        state = {'status': 'ok', 'requested_pages': pages, 'fetched_pages': 0,
                 'parsed_count': 0, 'duplicate_count': 0}
        seen = set()
        posts = []
        try:
            for page in range(1, pages + 1):
                html = fetch_board(cfg["code"], page)
                parsed = parse_posts(html)
                state['fetched_pages'] += 1
                state['parsed_count'] += len(parsed)
                if not parsed:
                    state['status'] = 'empty' if not posts else 'partial'
                new_count = 0
                for p in parsed:
                    key = p.get("id") or p.get("url") or p.get("title")
                    if key not in seen:
                        seen.add(key)
                        posts.append(p)
                        new_count += 1
                    else:
                        state['duplicate_count'] += 1
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
            state['status'] = 'partial' if posts else 'failed'
            state['error_type'] = type(e).__name__
        if report is not None:
            report[sector_key] = state
        # 板块之间加延迟
        _ad.sleep_like_human("scroll")
    return result


if __name__ == "__main__":
    data = collect_all()
    for k, v in data.items():
        print(f"{k}: {len(v)} posts")
