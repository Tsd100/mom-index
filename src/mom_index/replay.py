"""只读原始存档，离线规则重算；不覆盖生产记录、不调用LLM。"""
import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from mom_index.analyzer.llm_analyzer import analyze_post
from mom_index.analyzer.index_calculator import compute_sector_index
from mom_index.provenance import (SHANGHAI, now_local, prepare_posts, assess_valid_quality,
                                  verified_record, build_definition, digest)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replay(db_path, output_root, runs_dir=None):
    db_path, output_root = Path(db_path).resolve(), Path(output_root).resolve()
    runs_dir = Path(runs_dir or db_path.parent / 'runs')
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    if output_root == db_path.parent or output_root.is_relative_to(db_path.parent / 'production'):
        raise ValueError('重算输出必须与原始/生产目录分开')
    before = sha(db_path)
    connection = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        columns = {r[1] for r in connection.execute('PRAGMA table_info(raw_posts)')}
        run_column = 'run_id' if 'run_id' in columns else 'NULL'
        rows = connection.execute(f'SELECT id, collected_at, sector, platform, raw, {run_column} FROM raw_posts ORDER BY id').fetchall()
    finally:
        connection.close()
    rows_digest = digest(rows)
    grouped, invalid = defaultdict(list), []
    for row in rows:
        row_id, collected_at, sector, platform, raw, run_id = row
        try:
            post = json.loads(raw)
            if not isinstance(post, dict):
                raise ValueError('原始载荷不是对象')
            post.setdefault('platform', platform or 'unknown')
            group = run_id or 'legacy:' + collected_at[:10]
            grouped[group].append((row_id, collected_at, sector, post))
        except (ValueError, TypeError):
            invalid.append(row_id)
    rule = build_definition(pages=None)
    rule.pop('id')
    rule['llm'] = {'enabled': False, 'method': 'pure_rule_analyze_post'}
    rule['replay_code_hash'] = sha(__file__)
    rule_id = digest(rule)
    audit_hashes = {p.name: sha(p) for p in sorted(runs_dir.glob('*.json'))} if runs_dir.exists() else {}
    version = digest([before, rows_digest, rule_id, audit_hashes])[:24]
    target = output_root / version
    if target.exists():
        manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('source_db_sha256') != before or manifest.get('history_sha256') != sha(target / 'history.json'):
            raise ValueError('既有重算版本内容校验失败')
        return target
    records = []
    for group, entries in sorted(grouped.items()):
        original = {}
        audit_path = runs_dir / (group + '.json')
        if audit_path.exists():
            original = json.loads(audit_path.read_text(encoding='utf-8'))
        original_p = original.get('provenance', {})
        run_verified = (verified_record({'source': 'real', 'provenance': original_p})
                        and original_p.get('run_id') == group and bool(original_p.get('finished_at')))
        time_text = original_p.get('finished_at') or max(e[1] for e in entries)
        timestamp = datetime.fromisoformat(time_text)
        if timestamp.tzinfo is None:
            run_verified = False
            timestamp = timestamp.replace(tzinfo=SHANGHAI)
        timestamp = timestamp.astimezone(SHANGHAI)
        original_cfg = deepcopy(original_p.get('definition', {}).get('sectors', {}))
        sectors, analyses, details = {}, {}, {}
        mocks = duplicates = 0
        for sector in sorted({e[2] for e in entries}):
            posts = [e[3] for e in entries if e[2] == sector]
            accepted, quality = prepare_posts(posts, timestamp)
            mocks += quality['mock_excluded']; duplicates += quality['duplicate_count']
            old_q = original.get('quality', {}).get(sector, {})
            matched = bool(old_q.get('sample_digest')) and old_q['sample_digest'] == quality['sample_digest']
            if not matched:
                run_verified = False
            if old_q.get('collection_status') in ('failed', 'partial', 'empty') or old_q.get('failed_sources'):
                quality.update(status='collection_failed', reasons=['原采集来源失败或不完整'])
            results = [analyze_post(post, sector) for post in accepted]
            quality = assess_valid_quality(accepted, results, quality, timestamp)
            result = compute_sector_index(results)
            cfg = original_cfg.get(sector, {})
            board = cfg.get('code', '')
            instrument = {**cfg, 'previous_price_etf': cfg.get('etf'), 'etf': board[2:]} if board.startswith('of') else {}
            definition_id = digest([rule_id, original_p.get('definition', {}).get('id'), instrument, sorted({p.get('platform') for p in accepted})])
            result.update(quality=quality, definition_id=definition_id, instrument=instrument)
            if quality['status'] != 'ok':
                result.update(index=None, interpretation='数据不足，暂停情绪判断')
            sectors[sector] = result
            analyses[sector] = [asdict(r) for r in results]
            details[sector] = {'sample_digest_matched': matched, 'sample_digest': quality['sample_digest']}
        records.append({'date': timestamp.date().isoformat(), 'timestamp': timestamp.isoformat(),
                        'source': 'reconstructed' if run_verified else 'reconstructed_unverified',
                        'provenance': {'schema_version': 2, 'run_id': group, 'mock_excluded': True,
                                       'finished_at': timestamp.isoformat(),
                                       'definition': {'id': rule_id, 'sectors': original_cfg, 'rule': rule}},
                        'sectors': sectors, 'analysis': analyses,
                        'audit': {'original_run_verified': run_verified, 'original_provenance': original_p,
                                  'source_group': group, 'raw_row_ids': [e[0] for e in entries],
                                  'mock_excluded': mocks, 'duplicates_excluded': duplicates,
                                  'sector_checks': details,
                                  'limitations': [] if run_verified else ['旧数据不能可靠复原单次采集、标的或来源证明；仅供审计研究']}})
    if sha(db_path) != before:
        raise RuntimeError('重算期间原始数据库变化，未发布结果，请在采集结束后重试')
    if audit_hashes != ({p.name: sha(p) for p in sorted(runs_dir.glob('*.json'))} if runs_dir.exists() else {}):
        raise RuntimeError('重算期间来源运行记录变化，未发布结果')
    target.mkdir(parents=True)
    (target / 'history.json').write_text(json.dumps({'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = {'version': version, 'created_at': now_local().isoformat(), 'source_db_sha256': before,
                'raw_rows_digest': rows_digest,
                'rule_id': rule_id, 'source_runs_sha256': audit_hashes, 'records': len(records),
                'verified_runs': sum(r['audit']['original_run_verified'] for r in records),
                'unverified_runs': sum(not r['audit']['original_run_verified'] for r in records),
                'invalid_raw_row_ids': invalid, 'history_sha256': sha(target / 'history.json')}
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'重算 {len(records)} 组；可追溯运行 {manifest["verified_runs"]}；未核验 {manifest["unverified_runs"]}；输出 {target}')
    return target


if __name__ == '__main__':
    import os
    default = Path(os.environ.get('MOM_INDEX_DATA_DIR', Path(__file__).resolve().parents[1] / 'data'))
    parser = argparse.ArgumentParser(description='只读原始存档，输出隔离的规则重算版本')
    parser.add_argument('--db', type=Path, default=Path(os.environ.get('MOM_INDEX_DB_PATH', default / 'raw_posts.db')))
    parser.add_argument('--output', type=Path, default=default / 'reconstructed')
    parser.add_argument('--runs-dir', type=Path, default=default / 'runs')
    args = parser.parse_args()
    replay(args.db, args.output, args.runs_dir)
