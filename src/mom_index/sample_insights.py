"""独立样本观察、公式核对和每日最终快照质量；不改变正式指数。"""
from math import isfinite

from mom_index.provenance import (FRESH_HOURS, MIN_POSTS, is_mock, now_local,
                                  parse_list_time, post_key, record_expired, verified_record)

COMPONENT_VERSION = 'weighted-features-v1'
COMPONENT_LABELS = {'feature_share':'特征帖占比', 'feature_strength':'平均特征分',
                    'emotion_extremity':'情绪极端度', 'feature_purity':'高分特征帖占比'}


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def recent_observation(posts, results, quality, now=None):
    now = now or now_local()
    analyzed = {f'{r.platform}:{r.post_id}':r for r in results if r.level != '垃圾帖'}
    seen, recent = set(), []
    valid = unknown = 0
    for post in posts:
        key = post_key(post)
        if is_mock(post) or key in seen or key not in analyzed:
            continue
        seen.add(key)
        valid += 1
        timestamp = parse_list_time(post.get('list_updated_at', post.get('date')), now)
        if timestamp is None or timestamp > now:
            unknown += 1
        elif (now-timestamp).total_seconds() <= FRESH_HOURS*3600:
            recent.append(analyzed[key])
    complete = quality.get('collection_status') == 'ok' and not quality.get('failed_sources')
    status = 'source_unavailable' if not complete else 'ok' if len(recent) >= MIN_POSTS else 'insufficient'
    return {'version':'recent-updated-v1', 'as_of':now.isoformat(), 'window_hours':FRESH_HOURS,
            'time_basis':'list_updated_at_not_publication', 'status':status,
            'valid_count':valid, 'recent_count':len(recent), 'unknown_time_count':unknown,
            'recent_ratio':round(len(recent)/valid,4) if valid else None,
            'directions':{key:sum(r.intent == key for r in recent) for key in ('buy','sell','neutral')}
                         if status == 'ok' else None,
            'mean_sentiment':round(sum(r.sentiment_score for r in recent)/len(recent),4)
                              if status == 'ok' else None}


def component_change(current, previous):
    unavailable = {'status':'unavailable', 'reason':'缺少同版本完整分量或分量与总分不一致'}
    values = []
    for sector in (current,previous):
        node = sector.get('score_components') or {}
        parts = node.get('values') or {}
        if (node.get('version') != COMPONENT_VERSION or set(parts) != set(COMPONENT_LABELS)
                or not all(finite_number(v) and v >= 0 for v in parts.values())
                or not finite_number(sector.get('index'))
                or round(sum(parts.values()),1) != sector['index']):
            return unavailable
        values.append(parts)
    items = [{'key':key, 'label':label, 'change':round(values[0][key]-values[1][key],4)}
             for key,label in COMPONENT_LABELS.items()]
    residual = round(current['index']-previous['index']-sum(item['change'] for item in items),4)
    return {'status':'ok','items':items,'rounding_residual':residual}


def quality_overview(records):
    # 每天仅用最终快照；同日重试不计为多个观测日。原始运行文件与帖子不公开。
    daily = {r['date']:r for r in records if verified_record(r)}
    ordered = [daily[day] for day in sorted(daily)]
    latest = ordered[-1] if ordered else {}
    expired = record_expired(latest)
    rows = {}
    for sector,current in latest.get('sectors',{}).items():
        q = current.get('quality') or {}
        last_success = last_qualified = None
        streak = 0
        for record in ordered:
            old = record.get('sectors',{}).get(sector,{})
            quality = old.get('quality') or {}
            if quality.get('collection_status') == 'ok' and not quality.get('failed_sources'):
                last_success = record.get('provenance',{}).get('finished_at')
            if quality.get('status') == 'ok' and finite_number(old.get('index')):
                last_qualified = record.get('provenance',{}).get('finished_at')
        for record in reversed(ordered):
            quality = record.get('sectors',{}).get(sector,{}).get('quality') or {}
            if (quality.get('collection_status') in ('failed','partial','empty')
                    or quality.get('status') == 'collection_failed'):
                streak += 1
            else:
                break
        collection = q.get('collection_status','unknown')
        if q.get('failed_sources') and collection == 'ok':
            collection = 'partial'
        rows[sector] = {'status':q.get('status','unknown'), 'collection_status':collection,
                        'failed_sources':list(q.get('failed_sources') or []),
                        'reasons':q.get('reasons') or [], 'sample_count':q.get('sample_count'),
                        'valid_count':q.get('valid_count'), 'recent_count':q.get('valid_fresh_count'),
                        'last_collection_success_at':last_success, 'last_qualified_at':last_qualified,
                        'consecutive_failed_observations':streak}
    return {'date':latest.get('date'), 'as_of':latest.get('provenance',{}).get('finished_at'),
            'expired':expired, 'observed_dates':len(ordered), 'unit':'daily_final_snapshots',
            'current_qualified_count':sum(q['status']=='ok' for q in rows.values()) if not expired else 0,
            'total_count':len(rows), 'sectors':rows}
