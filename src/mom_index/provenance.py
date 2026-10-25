"""生产数据来源证明、口径指纹和快照质量。保守处理不能确认的日期。"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8))
SCHEMA_VERSION = 2
MIN_POSTS = 30
FRESH_HOURS = 24
SCORING_RULE_VERSION = 'scoring-v2-expression-context'
SAMPLING_RULE_VERSION = 'board-snapshot-v2'


def now_local():
    return datetime.now(SHANGHAI)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def is_mock(post):
    return (post.get('source') in ('mock', 'demo') or post.get('is_mock') is True
            or str(post.get('id', '')).startswith('xhs_sim_'))


def post_key(post):
    platform = post.get('platform', 'unknown')
    identity = post.get('id') or post.get('url') or digest([post.get('title'), post.get('author')])
    return f'{platform}:{identity}'


def build_definition(pages=3):
    from mom_index.collectors.guba_collector import SECTORS
    root = Path(__file__).parent
    files = ['analyzer/llm_analyzer.py', 'analyzer/text_rules.py', 'analyzer/index_calculator.py',
             'collectors/guba_collector.py', 'collectors/anti_detection.py', 'collectors/xhs_collector.py',
             'collectors/xueqiu_collector.py', 'pipeline.py', 'analyzer/signal.py', 'daily_summary.py', 'instruments.py', 'provenance.py']
    rules = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    # 人工维护的语义版本用于跨运行可比性；audit_id 则保留所有源文件的完整指纹。
    semantic = {
        'version': 'snapshot-v3',
        'scoring_rule_version': SCORING_RULE_VERSION,
        'sampling_rule_version': SAMPLING_RULE_VERSION,
        'pages': pages, 'sectors': SECTORS,
        'sampling': 'deduplicated_board_snapshot', 'fresh_hours': FRESH_HOURS,
        'minimum_valid_posts': MIN_POSTS, 'minimum_known_time_ratio': 0.8,
        'minimum_fresh_ratio': 0.5,
        'llm': {'enabled': bool(os.environ.get('MOM_INDEX_LLM_API_KEY')),
                'model': os.environ.get('MOM_INDEX_LLM_MODEL', 'gpt-4o-mini'),
                'endpoint_hash': digest(os.environ.get('MOM_INDEX_LLM_BASE_URL', 'https://api.openai.com/v1')),
                'rate': os.environ.get('MOM_INDEX_LLM_SAMPLE_RATE', '0.05')},
        'sources': {'xhs_enabled': bool(os.environ.get('RNODE_API_KEY')),
                    'xueqiu_enabled': os.environ.get('MOM_INDEX_ENABLE_XUEQIU') == '1'},
    }
    audit = {**semantic, 'rule_hashes': rules}
    return {'id': digest(semantic), 'audit_id': digest(rules), **audit}


def parse_list_time(value, now):
    text = str(value or '').strip()
    try:
        if re.fullmatch(r'\d{2}-\d{2} \d{2}:\d{2}', text):
            parsed = datetime.strptime(f'{now.year}-{text}', '%Y-%m-%d %H:%M').replace(tzinfo=SHANGHAI)
            if parsed > now + timedelta(minutes=5):
                parsed = parsed.replace(year=now.year - 1)
        elif re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}', text):
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SHANGHAI)
        else:
            return None
        return parsed if parsed <= now + timedelta(minutes=5) else None
    except (ValueError, TypeError):
        return None


def prepare_posts(posts, now=None, seen_ids=None):
    now = now or now_local()
    seen_ids = seen_ids or set()
    accepted, unique, ages = [], set(), []
    duplicates = mocks = unknown = newly_seen = 0
    for post in posts:
        if is_mock(post):
            mocks += 1
            continue
        if not post.get('title'):
            continue
        key = post_key(post)
        if key in unique:
            duplicates += 1
            continue
        unique.add(key)
        newly_seen += key not in seen_ids
        accepted.append({**post, 'source': 'real'})
        updated = parse_list_time(post.get('list_updated_at', post.get('date')), now)
        if updated is None:
            unknown += 1
        else:
            ages.append(max(0, (now - updated).total_seconds() / 3600))
    fresh = sum(age <= FRESH_HOURS for age in ages)
    quality = {
        'status': 'ok', 'reasons': [], 'raw_count': len(posts), 'sample_count': len(accepted),
        'duplicate_count': duplicates, 'mock_excluded': mocks,
        'duplicate_rate': round(duplicates / max(len(posts) - mocks, 1), 4),
        'newly_seen_count': newly_seen, 'previously_seen_count': len(accepted) - newly_seen,
        'fresh_count': fresh, 'unknown_time_count': unknown,
        'oldest_age_hours': round(max(ages), 1) if ages else None,
        'newest_age_hours': round(min(ages), 1) if ages else None,
        'time_basis': 'list_updated_at_not_publication', 'sample_digest': digest(sorted(unique)),
    }
    if len(accepted) < MIN_POSTS:
        quality.update(status='insufficient', reasons=['有效样本不足 30 条'])
    elif unknown / len(accepted) > 0.2:
        quality.update(status='unknown_time', reasons=['超过 20% 样本时间无法确认'])
    elif fresh / len(accepted) < 0.5:
        quality.update(status='stale', reasons=['24 小时内更新样本不足一半'])
    return accepted, quality


def verified_record(record):
    p = record.get('provenance', {})
    return (record.get('source') == 'real' and p.get('schema_version') == SCHEMA_VERSION
            and p.get('mock_excluded') is True and bool(p.get('run_id'))
            and bool(p.get('definition', {}).get('id')))


def assess_valid_quality(posts, results, quality, now=None):
    """垃圾帖不可贡献有效样本的新鲜度；分析结果已按分数排序，按身份关联。"""
    valid = {f'{r.platform}:{r.post_id}' for r in results if r.level != '垃圾帖'}
    rows = [p for p in posts if post_key(p) in valid]
    _, checked = prepare_posts(rows, now)
    output = {**quality, 'valid_count': len(rows),
              'valid_fresh_count': checked['fresh_count'],
              'valid_unknown_time_count': checked['unknown_time_count']}
    if quality.get('status') != 'collection_failed':
        output.update(status=checked['status'], reasons=checked['reasons'])
    return output


def record_expired(record, now=None):
    now = now or now_local()
    try:
        timestamp = datetime.fromisoformat(record['provenance']['finished_at'])
        return timestamp.tzinfo is None or not 0 <= (now - timestamp).total_seconds() <= FRESH_HOURS * 3600
    except (KeyError, TypeError, ValueError):
        return True


def eligible_sector(record, sector):
    return verified_record(record) and sector.get('quality', {}).get('status') == 'ok' and sector.get('index') is not None
