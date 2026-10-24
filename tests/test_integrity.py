import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from mom_index.analyzer import index_calculator as calc
from mom_index.analyzer.signal import generate_signals


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = patch.object(calc, 'DATA_DIR', self.temp.name)
        self.override.start()
        self.addCleanup(self.override.stop)

    def test_legacy_and_mock_history_cannot_enter_production(self):
        records = [
            {'date': '2026-08-02', 'source': 'real', 'sectors': {'gold': {'index': 30}}},
            {'date': '2026-08-03', 'source': 'mock', 'sectors': {'gold': {'index': 40}}},
        ]
        calc.save_history({'records': records})
        before = Path(self.temp.name, 'history.json').read_bytes()
        result = calc.get_dashboard_data()
        self.assertIsNone(result['latest'])
        self.assertEqual(result['sector_history']['gold'], [])
        self.assertEqual(before, Path(self.temp.name, 'history.json').read_bytes())
        self.assertEqual(result['excluded_records'], {'mock': 1, 'unverified': 1})

    def test_no_samples_must_not_be_zero_sentiment(self):
        self.assertIsNone(calc.compute_sector_index([])['index'])

    def test_quality_and_definition_gate_signals(self):
        dashboard = {
            'latest': {'date': '2026-10-15', 'provenance': {'finished_at': datetime.now().astimezone().isoformat()}, 'sectors': {
                'gold': {'index': 12, 'quality': {'status': 'stale', 'reasons': ['样本陈旧']}},
                'chip': {'index': 30, 'quality': {'status': 'ok'}, 'definition_id': 'new'},
            }},
            'real_dates': ['2026-10-14', '2026-10-15'],
            'sector_history': {'chip': [
                {'date': '2026-10-14', 'index': 70, 'definition_id': 'old'},
                {'date': '2026-10-15', 'index': 30, 'definition_id': 'new'},
            ]},
        }
        signals = {s['sector']: s for s in generate_signals(dashboard)}
        self.assertEqual(signals['gold']['level'], 'unavailable')
        self.assertNotIn('冷清', signals['gold']['action'])
        self.assertIsNone(signals['chip']['delta'])
        dashboard['sector_history']['chip'][0]['definition_id'] = 'new'
        self.assertEqual({s['sector']: s for s in generate_signals(dashboard)}['chip']['delta'], -40)
        dashboard['latest']['provenance']['finished_at'] = '2020-01-01T00:00:00+08:00'
        self.assertEqual({s['sector']: s for s in generate_signals(dashboard)}['chip']['level'], 'unavailable')

    def test_price_signal_requires_current_mapping_and_recent_bars(self):
        from datetime import timedelta
        from mom_index.provenance import SHANGHAI

        def dashboard_for(captured_etf, age_days):
            now = datetime.now(SHANGHAI)
            latest_day = now.date()
            finished = now.replace(hour=16, minute=0, second=0, microsecond=0)
            bars = []
            for offset in range(5, -1, -1):
                day = latest_day - timedelta(days=offset + age_days)
                bars.append({'date': day.isoformat(), 'price': 1 + (5 - offset) * 0.1, 'etf': '159206'})
            return {
                'latest': {'date': latest_day.isoformat(),
                           'provenance': {'finished_at': finished.isoformat()},
                           'sectors': {'aerospace': {'index': 50, 'quality': {'status': 'ok'},
                               'instrument': {'etf': captured_etf}}}},
                'instruments': {'aerospace': {'etf': '159206'}},
                'price_history': {'aerospace': bars},
            }

        with patch('mom_index.analyzer.signal.record_expired', return_value=False):
            current = {row['sector']: row for row in generate_signals(dashboard_for('159206', 0))}['aerospace']
            old_mapping = {row['sector']: row for row in generate_signals(dashboard_for('512710', 0))}['aerospace']
            stale_quotes = {row['sector']: row for row in generate_signals(dashboard_for('159206', 9))}['aerospace']
        self.assertIn('价格近 5 日上涨', current['extras'])
        self.assertNotIn('价格近 5 日上涨', old_mapping['extras'])
        self.assertNotIn('价格近 5 日上涨', stale_quotes['extras'])

    def test_intraday_signal_ignores_same_day_unfinished_close(self):
        from datetime import timedelta
        from mom_index.provenance import SHANGHAI

        finished = datetime.now(SHANGHAI).replace(hour=10, minute=0, second=0, microsecond=0)
        day = finished.date()
        bars = [
            {'date': (day - timedelta(days=offset)).isoformat(),
             'price': 120 if offset == 0 else 100, 'etf': '159206'}
            for offset in range(6, -1, -1)
        ]
        dashboard = {
            'latest': {'date': day.isoformat(), 'provenance': {'finished_at': finished.isoformat()},
                       'sectors': {'aerospace': {'index': 50, 'quality': {'status': 'ok'},
                           'instrument': {'etf': '159206'}}}},
            'instruments': {'aerospace': {'etf': '159206'}},
            'price_history': {'aerospace': bars},
        }
        with patch('mom_index.analyzer.signal.record_expired', return_value=False):
            signal = generate_signals(dashboard)[0]
        self.assertNotIn('价格近 5 日上涨', signal['extras'])

    def test_top_post_retains_original_source_url(self):
        from mom_index.analyzer.llm_analyzer import AnalysisResult
        source_url = 'https://guba.eastmoney.com/news,sh518880,1.html'
        result = AnalysisResult(post_id='guba_1', title='新手请教怎么买', platform='guba', sector='gold',
                                newbie_score=80, level='纯小白', reasoning='命中知识求助',
                                intent='buy', key_signals=['知识求助'], source_url=source_url)
        summary = calc.compute_sector_index([result])
        self.assertEqual(summary['top_newbie_posts'][0]['source_url'], source_url)

    def test_quality_tracks_unknown_time_duplicates_and_mock(self):
        from mom_index.provenance import prepare_posts
        now = datetime.fromisoformat('2026-10-15T10:00:00+08:00')
        rows = [
            {'id': 'guba_1', 'title': '新手', 'date': '10-15 09:00', 'platform': 'guba'},
            {'id': 'guba_1', 'title': '新手', 'date': '10-15 09:00', 'platform': 'guba'},
            {'id': 'guba_2', 'title': '旧帖', 'date': '未知', 'platform': 'guba'},
            {'id': 'xhs_sim_gold_1', 'title': '模拟', 'platform': 'xiaohongshu'},
        ]
        accepted, q = prepare_posts(rows, now, seen_ids={'guba:guba_1'})
        self.assertEqual(len(accepted), 2)
        self.assertEqual(q['mock_excluded'], 1)
        self.assertEqual(q['duplicate_count'], 1)
        self.assertEqual(q['newly_seen_count'], 1)
        self.assertEqual(q['unknown_time_count'], 1)
        self.assertEqual(q['fresh_count'], 1)
        self.assertEqual(q['time_basis'], 'list_updated_at_not_publication')
        self.assertEqual(q['status'], 'insufficient')

    def test_definition_changes_on_sampling_and_rules(self):
        from mom_index.provenance import build_definition
        a = build_definition(pages=3)
        self.assertEqual(a, build_definition(pages=3))
        different_sampling = build_definition(pages=1)
        self.assertNotEqual(a['id'], different_sampling['id'])
        self.assertEqual(a['audit_id'], different_sampling['audit_id'])
        original_read = Path.read_bytes

        def with_audit_only_comment(path):
            content = original_read(path)
            return content + b'\n# audit-only comment\n' if path.name == 'signal.py' else content

        with patch.object(Path, 'read_bytes', with_audit_only_comment):
            audit_only_change = build_definition(pages=3)
        self.assertEqual(a['id'], audit_only_change['id'])
        self.assertNotEqual(a['audit_id'], audit_only_change['audit_id'])
        with patch('mom_index.provenance.SCORING_RULE_VERSION', 'scoring-v2'):
            semantic_change = build_definition(pages=3)
        self.assertNotEqual(a['id'], semantic_change['id'])
        self.assertNotIn('api_key', json.dumps(a).lower())

    def test_freshness_and_year_boundary(self):
        from mom_index.provenance import prepare_posts, parse_list_time
        now = datetime.fromisoformat('2026-01-01T10:00:00+08:00')
        self.assertEqual(parse_list_time('12-31 12:00', now).year, 2025)
        rows = [{'id': str(i), 'title': '帖子', 'date': '2025-12-01 12:00'} for i in range(35)]
        self.assertEqual(prepare_posts(rows, now)[1]['status'], 'stale')
        for row in rows:
            row['date'] = '未知'
        self.assertEqual(prepare_posts(rows, now)[1]['status'], 'unknown_time')
        for row in rows:
            row['date'] = '01-01 09:00'
        self.assertEqual(prepare_posts(rows, now)[1]['status'], 'ok')

    def test_pipeline_blocks_mock_and_persists_audit(self):
        from mom_index import pipeline, storage
        now = datetime.fromisoformat('2026-10-15T10:00:00+08:00')
        rows = [{'id': f'guba_{i}', 'title': '小白请教还能买吗',
                 'date': '10-15 09:00', 'platform': 'guba'} for i in range(35)]

        def guba(report):
            report['gold'] = {'status': 'ok', 'parsed_count': 35, 'duplicate_count': 0}
            return {'gold': rows}

        mock_rows = {'gold': [{'id': 'xhs_sim_gold_0', 'title': '模拟帖', 'platform': 'xiaohongshu'}]}
        with patch.object(pipeline, 'DATA_DIR', self.temp.name), \
             patch.object(storage, 'DB_PATH', str(Path(self.temp.name, 'raw.db'))), \
             patch.object(pipeline, 'now_local', return_value=now), \
             patch.object(pipeline, 'collect_guba', side_effect=guba), \
             patch.object(pipeline, 'collect_xhs', return_value=mock_rows), \
             patch.object(pipeline, 'collect_xueqiu', return_value={}), \
             patch.object(pipeline, 'fetch_all_prices', return_value={'gold': 9.0}), \
             patch.dict('os.environ', {'MOM_INDEX_LLM_API_KEY': ''}):
            result = pipeline.run_pipeline(publish=False)
            quality = result['latest']['sectors']['gold']['quality']
            self.assertEqual(quality['mock_excluded'], 1)
            self.assertEqual(quality['sample_count'], 35)
            self.assertEqual(quality['status'], 'ok')
            self.assertIsNotNone(result['latest']['sectors']['gold']['index'])
            self.assertEqual(len(list(Path(self.temp.name, 'runs').glob('*.json'))), 1)
            audit = json.loads(next(Path(self.temp.name, 'runs').glob('*.json')).read_text(encoding='utf-8'))
            self.assertEqual(audit['sectors']['gold']['index'], result['latest']['sectors']['gold']['index'])
            self.assertEqual(len(audit['analysis']['gold']), 35)
            self.assertEqual(storage.count_posts(), 35)
            import sqlite3
            with sqlite3.connect(storage.DB_PATH) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM demo_posts').fetchone()[0], 1)
            connection.close()
            self.assertEqual(result['record_count'], 1)
            self.assertEqual(len(result['sector_history']['gold']), 1)
            self.assertIsNone(result['latest']['sectors']['chip']['index'])
            second = pipeline.run_pipeline(publish=False)
            self.assertEqual(second['latest']['sectors']['gold']['quality']['newly_seen_count'], 0)
            with patch.object(pipeline, 'collect_xhs', side_effect=RuntimeError('failed')), \
                 patch.dict('os.environ', {'RNODE_API_KEY': 'test-only'}):
                third = pipeline.run_pipeline(publish=False)
            self.assertIsNone(third['latest']['sectors']['gold']['index'])
            self.assertIn('xhs', third['latest']['sectors']['gold']['quality']['failed_sources'])

    def test_backtest_rejects_legacy_and_bad_quality(self):
        from mom_index import backtest
        calc.save_history({'records': [{'date': '2026-08-02', 'source': 'real', 'sectors': {}}]})
        with patch.object(backtest, 'DATA_DIR', self.temp.name):
            self.assertEqual(backtest.load_history(), [])

    def test_demo_command_leaves_production_unchanged(self):
        import os
        import subprocess
        target = Path(self.temp.name, 'history.json')
        target.write_text('{"records": []}', encoding='utf-8')
        before = target.read_bytes()
        result = subprocess.run([__import__('sys').executable, '-m', 'mom_index.pipeline', '--demo'],
                                env={**os.environ, 'PYTHONPATH': 'src', 'MOM_INDEX_DATA_DIR': self.temp.name},
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue(Path(self.temp.name, 'demo', 'history.json').exists())

    def test_new_record_is_physically_separate_from_legacy(self):
        from mom_index.provenance import build_definition, SCHEMA_VERSION
        calc.save_history({'records': [{'date': '2026-08-02', 'source': 'mock', 'sectors': {}}]})
        before = Path(self.temp.name, 'history.json').read_bytes()
        calc.add_record({}, {}, provenance={'schema_version': SCHEMA_VERSION, 'mock_excluded': True,
                                           'run_id': 'test-run', 'definition': build_definition()})
        self.assertEqual(Path(self.temp.name, 'history.json').read_bytes(), before)
        production = json.loads(Path(self.temp.name, 'production', 'history.json').read_text(encoding='utf-8'))
        self.assertEqual(len(production['records']), 1)

    def test_collector_reports_partial_failure(self):
        from mom_index.collectors import guba_collector as collector
        report = {}
        with patch.object(collector, 'SECTORS', {'gold': {'name': '黄金', 'code': 'of518880'}}), \
             patch.object(collector, 'fetch_board', side_effect=['page', RuntimeError('failed')]), \
             patch.object(collector, 'parse_posts', return_value=[{'id': '1', 'title': '真实帖子'}]), \
             patch.object(collector._ad, 'sleep_like_human'):
            result = collector.collect_all(pages=3, report=report)
        self.assertEqual(len(result['gold']), 1)
        self.assertEqual(report['gold']['status'], 'partial')
        self.assertEqual(report['gold']['fetched_pages'], 1)

    def test_board_fields_stay_in_their_own_row(self):
        from mom_index.collectors.guba_collector import parse_posts
        html = '''<span class="l5">最后更新</span>
        <div class="articleh normal_post"><span class="l3"><a href="/news,sh518880,1.html" title="点击开始搜索">忽略</a></span><span class="l5">01-01 00:00</span></div>
        <div class="articleh normal_post"><span class="l1">123</span><span class="l2">4</span><span class="l3"><a href="/news,sh518880,2.html" title="小白&amp;请教">标题</a></span><span class="l4"><a><font>作者甲</font></a></span><span class="l5">10-15 19:09</span></div>'''
        rows = parse_posts(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['date'], '10-15 19:09')
        self.assertEqual(rows[0]['author'], '作者甲')
        self.assertEqual(rows[0]['reads'], '123')
        self.assertEqual(rows[0]['title'], '小白&请教')

    def test_identity_challenge_is_not_an_empty_board(self):
        from mom_index.collectors import guba_collector as collector
        from unittest.mock import Mock
        response = Mock(text='<html><title>身份核实</title><div id="root"></div></html>')
        with patch.object(collector.requests, 'get', return_value=response):
            with self.assertRaisesRegex(RuntimeError, '身份核实'):
                collector.fetch_board('of512710')

    def test_fresh_spam_cannot_make_stale_valid_samples_healthy(self):
        from mom_index.provenance import prepare_posts, assess_valid_quality
        from mom_index.analyzer.llm_analyzer import analyze_all
        now = datetime.fromisoformat('2026-10-15T10:00:00+08:00')
        rows = [{'id': str(i), 'title': '签到', 'date': '10-15 09:00', 'platform': 'guba'} for i in range(70)]
        rows += [{'id': f'old{i}', 'title': '小白请教还能买吗', 'date': '2026-09-01 10:00', 'platform': 'guba'} for i in range(30)]
        accepted, quality = prepare_posts(rows, now)
        results = analyze_all({'gold': accepted})['gold']
        checked = assess_valid_quality(accepted, results, quality, now)
        self.assertEqual(checked['status'], 'stale')
        self.assertEqual(checked['valid_fresh_count'], 0)

    def test_demo_backtest_cannot_overwrite_production_report(self):
        from mom_index import backtest
        prod = Path(self.temp.name, 'production')
        prod.mkdir()
        report = prod / 'backtest_report.md'
        report.write_text('正式报告', encoding='utf-8')
        calc.save_history({'records': [
            {'date': '2026-08-01', 'source': 'mock', 'sectors': {'gold': {'index': 30, 'price': 8}}},
            {'date': '2026-08-02', 'source': 'mock', 'sectors': {'gold': {'index': 40, 'price': 9}}},
        ]})
        with patch.object(backtest, 'DATA_DIR', self.temp.name):
            backtest.run(horizons=(1,), include_mock=True)
        self.assertEqual(report.read_text(encoding='utf-8'), '正式报告')
        self.assertTrue(Path(self.temp.name, 'demo', 'backtest_report.md').exists())


if __name__ == '__main__':
    unittest.main()
