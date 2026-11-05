import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mom_index.provenance import now_local, prepare_posts


class SourceReliabilityTests(unittest.TestCase):
    def test_business_error_reaches_pipeline_quality_gate(self):
        from mom_index import pipeline, storage
        from mom_index.analyzer import index_calculator as calc
        from mom_index.collectors import xhs_collector as xhs
        now=now_local()
        rows=[{'id':str(i),'title':'今天买入了','platform':'guba','date':now.isoformat()} for i in range(35)]
        def guba(report):
            report['gold']={'status':'ok'}
            return {'gold':rows}
        response=Mock(status_code=200);response.json.return_value={'success':False,'code':'quota_exceeded'}
        with tempfile.TemporaryDirectory() as root,patch.object(calc,'DATA_DIR',root),patch.object(pipeline,'DATA_DIR',root), \
             patch.object(storage,'DB_PATH',str(Path(root,'raw.db'))),patch.object(pipeline,'collect_guba',side_effect=guba), \
             patch.object(pipeline,'collect_xueqiu',return_value={}),patch.object(pipeline,'fetch_all_prices',return_value={}), \
             patch.object(xhs,'API_KEY','test-only'),patch.object(xhs,'SEARCH_KEYWORDS',{'gold':['test']}), \
             patch.object(xhs.requests,'get',return_value=response),patch.dict('os.environ',{'RNODE_API_KEY':'test-only'}):
            result=pipeline.run_pipeline(publish=False)['latest']['sectors']['gold']
        self.assertIsNone(result['index'])
        self.assertIn('xhs',result['quality']['failed_sources'])
        self.assertIsNone(result['recent_observation']['directions'])

    def test_xueqiu_business_error_is_not_empty_search(self):
        from mom_index.collectors import xueqiu_collector as xq
        response=Mock();response.json.return_value={'error_code':400016,'error_description':'test'}
        with patch.object(xq.requests,'get',return_value=response),self.assertRaises(ValueError):
            xq._search('test')

    def test_spam_never_reaches_model_or_becomes_valid(self):
        from mom_index.analyzer import llm_analyzer as analyzer
        post = {'id':'spam','platform':'guba','title':'签到领金条'}
        with patch.object(analyzer,'llm_spotcheck_enabled',return_value=True), patch('requests.post') as request:
            result = analyzer.analyze_sector([post],'gold')[0]
            result = analyzer.llm_rejudge(post,result)
        request.assert_not_called()
        self.assertEqual(result.level,'垃圾帖')

    def test_business_error_and_bad_schema_fail_but_valid_empty_is_empty(self):
        from mom_index.collectors import xhs_collector as xhs
        for payload, expected in [({'success':False,'code':'quota_exceeded'},'failed'),
                                  ({'data':{}},'failed'),
                                  ({'data':{'data':{'items':[]}}},'empty'),
                                  ({'success':False,'data':{'data':{'items':[]}}},'failed')]:
            with self.subTest(payload=payload):
                response=Mock(status_code=200); response.json.return_value=payload
                report=[]
                with patch.object(xhs,'API_KEY','test-only'),patch.object(xhs.requests,'get',return_value=response):
                    self.assertEqual(xhs.search_notes('test',report=report),[])
                self.assertEqual(report[0]['status'],expected)

    def test_adapters_keep_time_semantics_and_source_link(self):
        from mom_index.collectors import xhs_collector as xhs, xueqiu_collector as xq
        now=now_local(); millis=int(now.timestamp()*1000)
        note=xhs._parse_note({'id':'a','title':'已买入','time':millis,'url':'https://www.xiaohongshu.com/explore/a'})
        self.assertEqual(note['time_basis'],'publication')
        self.assertTrue(note['date'])
        self.assertEqual(note['url'],'https://www.xiaohongshu.com/explore/a')
        response=Mock();response.json.return_value={'list':[{'id':1,'title':'已买入','created_at':millis}]}
        with patch.object(xq.requests,'get',return_value=response):
            posts=xq._search('test')
        self.assertEqual(prepare_posts(posts,now)[1]['unknown_time_count'],0)
        self.assertEqual(prepare_posts(posts,now)[1]['time_basis'],'publication')
        unknown=xhs._parse_note({'id':'b','title':'无时间'})
        self.assertFalse(unknown['date'])

    def test_bad_market_file_does_not_block_dashboard(self):
        from mom_index.analyzer import index_calculator as calc
        for payload in ['{', '[]', '{}']:
            with self.subTest(payload=payload),tempfile.TemporaryDirectory() as directory,patch.object(calc,'DATA_DIR',directory):
                path=Path(directory,'market_history.json');path.write_text(payload,encoding='utf-8')
                dashboard=calc.get_dashboard_data()
                self.assertEqual(dashboard['market_status']['status'],'unavailable')
                self.assertEqual(path.read_text(encoding='utf-8'),payload)

    def test_interrupted_market_write_preserves_previous_file(self):
        from mom_index import market_data
        rows=[{'date':'2026-10-01','open':1,'close':1}]
        with tempfile.TemporaryDirectory() as directory,patch.object(market_data,'fetch_daily',return_value=rows):
            path=Path(directory,'market_history.json');path.write_text('previous',encoding='utf-8')
            original=Path.replace
            def interrupted(source,target):
                if Path(target)==path:
                    raise OSError('simulated interruption')
                return original(source,target)
            with patch.object(Path,'replace',interrupted):
                with self.assertRaises(OSError):
                    market_data.fetch_market(Path(directory))
            self.assertEqual(path.read_text(encoding='utf-8'),'previous')


if __name__=='__main__':
    unittest.main()
