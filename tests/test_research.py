import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


def sample_record(timestamp='2026-10-16T16:00:00+08:00', definition='v1', index=60):
    return {'date': timestamp[:10], 'source': 'real', 'provenance': {
        'schema_version': 2, 'mock_excluded': True, 'run_id': timestamp,
        'finished_at': timestamp, 'definition': {'id': definition,
            'sectors': {'gold': {'code': 'of518880', 'etf': '518880'}}}},
        'sectors': {'gold': {'index': index, 'definition_id': definition,
                             'quality': {'status': 'ok'}}}}


def market_fixture():
    dates = ['2026-10-08', '2026-10-09', '2026-10-12', '2026-10-13', '2026-10-14',
             '2026-10-15', '2026-10-16', '2026-10-19', '2026-10-20']
    rows = [{'date': d, 'open': 10 + i, 'close': 10.5 + i} for i, d in enumerate(dates)]
    return stamp_market({'schema_version': 1, 'source': 'tencent_fqkline', 'adjustment': 'qfq',
            'fetched_at': '2026-10-20T16:00:00+08:00', 'calendar_code': '510300',
            'instruments': {'518880': {'rows': rows}, '510300': {'rows': rows}}})


def stamp_market(market):
    from mom_index.provenance import digest
    market.pop('dataset_id', None)
    for node in market['instruments'].values():
        node['rows_hash'] = digest(node['rows'])
    market['dataset_id'] = digest(market)
    return market


class ResearchTests(unittest.TestCase):
    def test_mappings_use_the_same_board_and_price_instrument(self):
        from mom_index.instruments import SECTORS
        self.assertEqual(len(SECTORS), 12)
        self.assertTrue(all(c['code'] == 'of' + c['etf'] for c in SECTORS.values()))
        self.assertEqual(SECTORS['aerospace']['etf'], '159206')
        self.assertEqual(SECTORS['petrochemical']['etf'], '159731')
        self.assertEqual(SECTORS['nasdaq']['etf'], '159941')
        self.assertTrue(all(c['source_url'].startswith('https://') for c in SECTORS.values()))

    def test_next_session_open_prevents_same_close_lookahead(self):
        from mom_index.research import evaluate
        report = evaluate([sample_record()], market_fixture(), horizons=(1, 2))
        first = report['samples'][0]
        self.assertEqual(first['entry_date'], '2026-10-19')
        self.assertEqual(first['exit_date'], '2026-10-19')
        self.assertAlmostEqual(first['etf_return'], 17.5 / 17 - 1)
        self.assertAlmostEqual(first['benchmark_return'], first['etf_return'])
        self.assertEqual(first['sentiment_exposure'], 0)
        self.assertEqual(first['sentiment_return'], 0)
        self.assertAlmostEqual(first['momentum_return'], first['etf_return'])
        self.assertEqual(report['samples'][1]['exit_date'], '2026-10-20')

    def test_missing_bar_is_not_skipped_to_fake_a_trading_day(self):
        from mom_index.research import evaluate
        market = market_fixture()
        market['instruments']['518880']['rows'] = [r for r in market['instruments']['518880']['rows'] if r['date'] != '2026-10-19']
        stamp_market(market)
        report = evaluate([sample_record()], market, horizons=(1,))
        self.assertEqual(report['samples'], [])
        self.assertEqual(report['skipped']['missing_bar'], 1)

    def test_definitions_are_separate_and_duplicates_do_not_inflate_samples(self):
        from mom_index.research import evaluate
        a = sample_record()
        b = sample_record(definition='v2')
        report = evaluate([a, a, b], market_fixture(), horizons=(1,))
        self.assertEqual(len(report['samples']), 2)
        self.assertEqual(len(report['groups']), 2)
        self.assertEqual(report['skipped']['duplicate_signal'], 1)

    def test_unknown_time_and_legacy_and_wrong_etf_are_rejected(self):
        from mom_index.research import evaluate
        a = sample_record()
        del a['provenance']['finished_at']
        b = sample_record(); b['provenance']['definition']['sectors']['gold']['etf'] = '159941'
        report = evaluate([a, b, {'source': 'real', 'date': '2026-08-02', 'sectors': {'gold': {'index': 90}}}], market_fixture(), horizons=(1,))
        self.assertEqual(report['samples'], [])
        self.assertEqual(report['skipped']['unknown_signal_time'], 1)
        self.assertEqual(report['skipped']['instrument_mismatch'], 1)
        self.assertEqual(report['skipped']['unverified_record'], 1)

    def test_incomplete_current_day_is_excluded(self):
        from mom_index.market_data import completed_rows
        rows = [{'date': '2026-10-16', 'open': 10, 'close': 11},
                {'date': '2026-10-15', 'open': 9, 'close': 10}]
        now = datetime.fromisoformat('2026-10-16T14:00:00+08:00')
        self.assertEqual([r['date'] for r in completed_rows(rows, now)], ['2026-10-15'])

    def test_missing_market_proof_is_rejected(self):
        from mom_index.research import evaluate
        market = market_fixture()
        market.pop('dataset_id', None)
        with self.assertRaisesRegex(ValueError, '行情.*证明'):
            evaluate([sample_record()], market, horizons=(1,))
        from mom_index.provenance import digest
        market = market_fixture()
        market['instruments']['518880'].pop('rows_hash')
        market['dataset_id'] = digest({k: v for k, v in market.items() if k != 'dataset_id'})
        with self.assertRaisesRegex(ValueError, '行情摘要'):
            evaluate([sample_record()], market, horizons=(1,))

    def test_intraday_signal_momentum_does_not_use_todays_close(self):
        from mom_index.research import evaluate
        market = market_fixture()
        market['instruments']['518880']['rows'][6]['close'] = 1.0
        stamp_market(market)
        result = evaluate([sample_record('2026-10-16T10:00:00+08:00')], market, horizons=(1,))
        # 16日收盘暴跌尚未发生，不能改变当日10点看到的历史上涨动量。
        self.assertAlmostEqual(result['samples'][0]['momentum_return'], result['samples'][0]['etf_return'])

    def test_corrupted_market_content_is_rejected(self):
        from mom_index.research import evaluate
        market = market_fixture()
        market['instruments']['518880']['rows'][0]['close'] = 999.0
        with self.assertRaisesRegex(ValueError, '批次证明'):
            evaluate([sample_record()], market, horizons=(1,))

    def test_report_remains_explicitly_inconclusive_without_future(self):
        from mom_index.research import evaluate, render_report
        market = market_fixture()
        report = evaluate([sample_record('2026-10-20T16:00:00+08:00')], market, horizons=(5,))
        self.assertFalse(report['samples'])
        self.assertIn('样本不足', render_report(report))
        self.assertNotIn('反指成立', render_report(report))

    def test_old_mapping_is_not_replaced_by_current_satellite_etf(self):
        from mom_index.instruments import record_instrument
        record = sample_record()
        record['provenance']['definition']['sectors']['aerospace'] = {'code': 'of512710', 'etf': '512710'}
        self.assertEqual(record_instrument(record, 'aerospace')['etf'], '512710')

    def test_dashboard_does_not_mix_changed_etf_prices(self):
        from mom_index.analyzer import index_calculator as calc
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            record = sample_record()
            record['provenance']['definition']['sectors']['aerospace'] = {'code': 'of512710', 'etf': '512710'}
            record['sectors']['aerospace'] = {'index': 10, 'price': 1.0, 'definition_id': 'old', 'quality': {'status': 'ok'}}
            with patch.object(calc, 'DATA_DIR', root):
                calc.save_history({'records': [record]})
                Path(root, 'price_backfill.json').write_text(json.dumps({'aerospace': [{'date': '2026-10-15', 'price': 2.0}]}),encoding='utf-8')
                result = calc.get_dashboard_data()
                self.assertEqual(result['price_history']['aerospace'], [])
                self.assertEqual(result['latest']['sectors']['aerospace']['instrument']['etf'], '512710')
                self.assertEqual(result['instruments']['aerospace']['etf'], '159206')

    def test_replay_is_readonly_deduplicated_and_keeps_legacy_unverified(self):
        from mom_index.replay import replay
        with tempfile.TemporaryDirectory() as root:
            db = Path(root, 'raw.db')
            conn = sqlite3.connect(db)
            conn.execute('CREATE TABLE raw_posts (id INTEGER PRIMARY KEY, collected_at TEXT, sector TEXT, platform TEXT, raw TEXT, run_id TEXT)')
            real = {'id': 'guba_1', 'title': '小白请教还能买吗', 'platform': 'guba', 'date': '08-02 10:00', 'url': 'https://guba.eastmoney.com/news,sh518880,1.html'}
            mock = {'id': 'xhs_sim_gold_0', 'title': '模拟帖子', 'platform': 'xiaohongshu'}
            for row in [real, real, mock]:
                conn.execute('INSERT INTO raw_posts (collected_at,sector,platform,raw) VALUES (?,?,?,?)',
                             ('2026-08-02T16:00:00', 'gold', row['platform'], json.dumps(row)))
            conn.commit(); conn.close()
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            target = replay(db, Path(root, 'reconstructed'), runs_dir=Path(root, 'runs'))
            result = json.loads((target / 'history.json').read_text(encoding='utf-8'))
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)
            self.assertEqual(len(result['records']), 1)
            record = result['records'][0]
            self.assertEqual(record['source'], 'reconstructed_unverified')
            self.assertEqual(record['sectors']['gold']['quality']['sample_count'], 1)
            self.assertEqual(record['audit']['mock_excluded'], 1)
            self.assertEqual(record['audit']['duplicates_excluded'], 1)
            self.assertTrue((target / 'manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
