import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen


class NasRuntimeTests(unittest.TestCase):
    def test_request_compression_uses_installed_decoders(self):
        from mom_index.collectors.anti_detection import get_anti_detection
        self.assertNotIn('Accept-Encoding', get_anti_detection().get_common_headers())

    def test_complete_source_failure_is_distinct_from_stale_quality(self):
        from mom_index import nas_runtime as runtime
        with tempfile.TemporaryDirectory() as root, \
                patch.object(runtime, 'fetch_market', return_value={'failures': {}}), \
                patch.object(runtime, 'publish_dashboard'), \
                patch.object(runtime, 'run_pipeline') as collect:
            collect.return_value = {'latest': {'sectors': {'gold': {'quality': {'status': 'collection_failed'}}}}}
            failed = runtime.collect_once(Path(root), Path(root, 'public'))
            self.assertEqual(failed['status'], 'failed')
            collect.return_value = {'latest': {'sectors': {'gold': {'quality': {'status': 'stale'}}}}}
            self.assertEqual(runtime.collect_once(Path(root), Path(root, 'public'))['status'], 'partial')

    def test_package_contains_code_without_local_data_or_credentials(self):
        import runpy
        project = Path(__file__).resolve().parents[1]
        builder = runpy.run_path(str(project / 'nas-deploy-tool.py'))
        with tempfile.TemporaryDirectory() as root:
            target = builder['package_source'](Path(root, 'package'))
            files = [str(path.relative_to(target)).replace('\\', '/') for path in target.rglob('*') if path.is_file()]
            self.assertIn('src/mom_index/frontend/vendor/chart.umd.min.js', files)
            self.assertIn('docker-compose.yml', files)
            self.assertFalse(any('/data/' in path or path.endswith(('.db', '.json', '.env')) for path in files))

    def test_daily_schedule_catches_up_and_survives_restart(self):
        from mom_index.nas_runtime import next_attempt
        morning = datetime.fromisoformat('2026-10-24T09:00:00+08:00')
        self.assertEqual(next_attempt(morning, {}, '17:00', startup=True), morning)
        previous = {'last_started_at': morning.isoformat()}
        self.assertEqual(next_attempt(morning, previous, '17:00').hour, 17)
        evening = morning.replace(hour=19)
        self.assertEqual(next_attempt(evening, previous, '17:00'), evening)
        previous['scheduled_for'] = '2026-10-24'
        due = next_attempt(evening, previous, '17:00', startup=True)
        self.assertEqual(due.isoformat(), '2026-10-25T17:00:00+08:00')

    def test_failed_attempt_has_retry_before_tomorrows_schedule(self):
        from mom_index.nas_runtime import next_attempt
        now = datetime.fromisoformat('2026-10-24T17:05:00+08:00')
        state = {'scheduled_for': '2026-10-24', 'retry_at': '2026-10-24T17:20:00+08:00'}
        self.assertEqual(next_attempt(now, state, '17:00').minute, 20)

    def test_market_failure_does_not_prevent_sentiment_publication(self):
        from mom_index import nas_runtime as runtime
        dashboard = {'latest': {'sectors': {'gold': {'quality': {'status': 'ok'}}}}, 'record_count': 1}
        with tempfile.TemporaryDirectory() as root, \
                patch.object(runtime, 'fetch_market', side_effect=RuntimeError('private detail')), \
                patch.object(runtime, 'run_pipeline', return_value=dashboard) as collect, \
                patch.object(runtime, 'publish_dashboard') as publish:
            result = runtime.collect_once(Path(root), Path(root, 'public'))
            collect.assert_called_once_with(publish=False)
            publish.assert_called_once()
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['valid_sectors'], 1)
            self.assertNotIn('private detail', json.dumps(result))

    def test_web_keeps_private_storage_inaccessible(self):
        from mom_index.nas_runtime import make_web_server
        with tempfile.TemporaryDirectory() as root:
            public = Path(root, 'public'); public.mkdir()
            Path(root, 'raw_posts.db').write_text('private raw data')
            (public / 'history.json').write_text('private legacy data')
            (public / 'dashboard_data.json').write_text('{"schema_version":2,"mode":"production"}')
            server = make_web_server(public, '127.0.0.1', 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                origin = f'http://127.0.0.1:{server.server_address[1]}'
                self.assertEqual(urlopen(origin + '/dashboard.html').status, 200)
                self.assertEqual(urlopen(origin + '/healthz').status, 200)
                self.assertEqual(json.load(urlopen(origin + '/data/dashboard_data.json'))['schema_version'], 2)
                for path in ['/data/history.json', '/raw_posts.db', '/data/../raw_posts.db', '/data/']:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(origin + path)
                    self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
