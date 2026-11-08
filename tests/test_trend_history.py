import json
from pathlib import Path
import tempfile
import unittest
import os
import runpy
import subprocess
import sys
from unittest.mock import patch

from mom_index.analyzer import index_calculator as calc


class TrendHistoryTests(unittest.TestCase):
    def test_local_worker_can_import_package_from_another_working_directory(self):
        launcher=Path(__file__).resolve().parents[1]/'tools/local_service.py'
        functions=runpy.run_path(str(launcher))
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'PYTHONPATH':''}):
            functions['configure_environment']()
            result=subprocess.run([sys.executable,'-c','import mom_index.nas_runtime'],
                                  cwd=root,env=dict(os.environ),capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))

    def test_public_history_includes_date_evidence_without_rewriting_or_raw_analysis(self):
        def record(day,status):
            return {'date':day,'source':'real','provenance':{'schema_version':2,'mock_excluded':True,
                'run_id':day,'finished_at':day+'T17:00:00+08:00','definition':{'id':'same',
                'sectors':{'gold':{'code':'of518880','etf':'518880'}}}},
                'analysis':{'private':'not published'},'sectors':{'gold':{'index':45,'definition_id':'same',
                  'quality':{'status':status,'valid_count':35,'reasons':[]},
                  'details':{'mom_buy_index':20,'mom_sell_index':10},
                  'top_newbie_posts':[{'title':'已买入','source_url':'https://guba.eastmoney.com/news,1.html'}]}}}
        with tempfile.TemporaryDirectory() as root,patch.object(calc,'DATA_DIR',root):
            path=Path(root,'production/history.json');path.parent.mkdir()
            path.write_text(json.dumps({'records':[record('2026-11-01','ok'),record('2026-11-02','stale')]}),encoding='utf-8')
            original=path.read_bytes()
            history=calc.get_dashboard_data()['sector_history']['gold']
            self.assertEqual(history[0]['details']['mom_buy_index'],20)
            self.assertEqual(history[0]['instrument']['etf'],'518880')
            self.assertEqual(history[0]['observed_at'],'2026-11-01T17:00:00+08:00')
            self.assertEqual(history[0]['top_newbie_posts'][0]['title'],'已买入')
            self.assertIsNone(history[1]['index'])
            self.assertNotIn('analysis',json.dumps(history))
            self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':
    unittest.main()
