"""从已核验看板快照生成每日变化，不联网、不重算历史、不推断涨跌。"""
from copy import deepcopy
from math import isfinite

from mom_index.provenance import record_expired


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def comparable_previous(dashboard, sector, current):
    """只比较紧邻上期，不能跨过质量缺口、口径切换或未来日期。"""
    day = (dashboard.get('latest') or {}).get('date', '')
    points = sorted((p for p in dashboard.get('sector_history', {}).get(sector, [])
                     if p.get('date', '') <= day), key=lambda p: p.get('date', ''))
    if len(points) < 2:
        return None
    previous, latest = points[-2:]
    definition = current.get('definition_id')
    if (latest.get('date') != day or previous.get('date', '') >= day
            or not valid_number(previous.get('index')) or not valid_number(current.get('index'))
            or latest.get('index') != current['index'] or not definition
            or latest.get('definition_id') != definition or previous.get('definition_id') != definition
            or previous.get('date') not in dashboard.get('real_dates', [])):
        return None
    return previous


def build_daily_summary(dashboard):
    latest = dashboard.get('latest') or {}
    result = {'status': 'waiting', 'date': latest.get('date'), 'available_count': 0,
              'total_count': len(latest.get('sectors', {})), 'highlights': [],
              'unavailable': [], 'not_comparable': []}
    if not latest:
        return result
    expired = record_expired(latest)
    result['status'] = 'expired' if expired else 'ready'
    changes = []
    for sector, current in latest.get('sectors', {}).items():
        quality = current.get('quality', {})
        if expired or quality.get('status') != 'ok' or not valid_number(current.get('index')):
            reason = '采集结果过期或时间未核验' if expired else '；'.join(quality.get('reasons') or ['样本质量未核验'])
            result['unavailable'].append({'sector': sector, 'reason': reason})
            continue
        result['available_count'] += 1
        previous = comparable_previous(dashboard, sector, current)
        if previous is None:
            result['not_comparable'].append({'sector': sector, 'reason': '无紧邻同口径有效上期记录'})
            continue
        changes.append({'sector': sector, 'index': current['index'],
                        'delta': round(current['index'] - previous['index'], 1),
                        'comparison_date': previous['date'],
                        'valid_count': quality.get('valid_count', 0),
                        'sample_count': quality.get('sample_count', 0),
                        'evidence': [{key: deepcopy(post.get(key, ''))
                                      for key in ('title', 'source_url', 'reasoning', 'intent_basis')}
                                     for post in current.get('top_newbie_posts', [])[:3]]})
    result['highlights'] = sorted(changes, key=lambda row: (-abs(row['delta']), row['sector']))[:3]
    return result
