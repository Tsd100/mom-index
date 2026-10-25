import copy
import unittest
from datetime import timedelta
from dataclasses import replace

from mom_index.provenance import now_local
from mom_index.analyzer.llm_analyzer import analyze_post
from mom_index.analyzer.index_calculator import compute_sector_index


def observation_input(count=30):
    now = now_local()
    posts = [{'id': str(i), 'platform': 'guba', 'title': '今天已买入',
              'list_updated_at': (now-timedelta(hours=1)).isoformat()} for i in range(count)]
    results = [analyze_post(post, 'gold') for post in posts]
    return now, posts, results


def record(day, collection='ok', quality='ok'):
    timestamp = (now_local()-timedelta(days=day)).isoformat()
    return {'date':timestamp[:10], 'source':'real', 'provenance':{
        'schema_version':2,'mock_excluded':True,'run_id':str(day),
        'definition':{'id':'same'},'finished_at':timestamp},
        'sectors':{'gold':{'index':40 if quality=='ok' else None,
                          'quality':{'status':quality,'collection_status':collection,
                                     'valid_count':100,'valid_fresh_count':35}}}}


class RecentObservationTests(unittest.TestCase):
    def observe(self, posts, results, now, quality=None):
        from mom_index.sample_insights import recent_observation
        return recent_observation(posts, results, quality or {'collection_status':'ok'}, now)

    def test_recent_subset_survives_old_majority_without_replacing_index(self):
        now, posts, results = observation_input()
        old = {**posts[0], 'id':'old','list_updated_at':(now-timedelta(days=3)).isoformat()}
        posts += [old]
        results += [analyze_post(old,'gold')]
        result = self.observe(posts, list(reversed(results)), now)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['recent_count'],30)
        self.assertEqual(result['valid_count'],31)
        self.assertEqual(result['directions'],{'buy':30,'sell':0,'neutral':0})
        self.assertNotIn('index',result)

    def test_mock_spam_duplicate_unknown_and_future_do_not_fill_recent_sample(self):
        now, posts, results = observation_input(29)
        extras = [{**posts[0], 'id':'mock','source':'mock'},
                  {**posts[0], 'id':'spam','title':'签到'},
                  {**posts[0], 'id':'unknown','list_updated_at':'未知'},
                  {**posts[0], 'id':'future','list_updated_at':(now+timedelta(minutes=2)).isoformat()},
                  copy.deepcopy(posts[0])]
        result = self.observe(posts+extras,results+[analyze_post(p,'gold') for p in extras],now)
        self.assertEqual(result['recent_count'],29)
        self.assertEqual(result['status'],'insufficient')
        self.assertIsNone(result['directions'])
        self.assertIsNone(result['mean_sentiment'])

    def test_failed_or_unknown_collection_cannot_publish_recent_direction(self):
        now, posts, results = observation_input()
        for quality in [{'collection_status':'partial'}, {},
                        {'collection_status':'ok','failed_sources':['xhs']}]:
            result = self.observe(posts, results, now, quality={**quality,'test':True})
            self.assertEqual(result['status'],'source_unavailable')
            self.assertIsNone(result['directions'])


class ComponentTests(unittest.TestCase):
    def test_daily_summary_uses_previous_component_snapshot_and_definition_gate(self):
        from mom_index.daily_summary import build_daily_summary
        _,_,results = observation_input()
        before=compute_sector_index(results)
        after=compute_sector_index([replace(r,newbie_score=70,sentiment_score=-1) for r in results])
        now=now_local()
        previous=(now-timedelta(days=1)).date().isoformat()
        day=now.date().isoformat()
        after.update(quality={'status':'ok'},definition_id='same')
        data={'latest':{'date':day,'provenance':{'finished_at':now.isoformat()},'sectors':{'gold':after}},
              'real_dates':[previous,day], 'sector_history':{'gold':[
                  {**before,'date':previous,'definition_id':'same'},
                  {**after,'date':day,'definition_id':'same'}]}}
        self.assertEqual(build_daily_summary(data)['highlights'][0]['component_change']['status'],'ok')
        data['sector_history']['gold'][0]['definition_id']='old'
        self.assertEqual(build_daily_summary(data)['highlights'],[])

    def test_components_reconstruct_existing_score_and_change(self):
        from mom_index.sample_insights import component_change
        _, _, results = observation_input()
        before = compute_sector_index(results)
        after = compute_sector_index([replace(r,newbie_score=70,sentiment_score=-1) for r in results])
        self.assertAlmostEqual(round(sum(before['score_components']['values'].values()),1),before['index'])
        change = component_change(after,before)
        self.assertEqual(change['status'],'ok')
        self.assertAlmostEqual(sum(item['change'] for item in change['items'])+change['rounding_residual'],
                               after['index']-before['index'],places=4)

    def test_old_invalid_or_inconsistent_components_are_explicitly_unavailable(self):
        from mom_index.sample_insights import component_change
        _, _, results = observation_input()
        current=compute_sector_index(results)
        for previous in [{}, {'index':45,'score_components':{'version':'unknown','values':{}}},
                         {**current,'index':99}]:
            self.assertEqual(component_change(current,previous)['status'],'unavailable')


class QualityOverviewTests(unittest.TestCase):
    def test_other_source_failure_cannot_be_displayed_as_collection_success(self):
        from mom_index.sample_insights import quality_overview
        current=record(0, 'ok', 'collection_failed')
        current['sectors']['gold']['quality']['failed_sources']=['xhs']
        row=quality_overview([current])['sectors']['gold']
        self.assertEqual(row['collection_status'],'partial')
        self.assertEqual(row['failed_sources'],['xhs'])
        self.assertIsNone(row['last_collection_success_at'])

    def test_fetch_success_and_valid_sample_are_separate_and_failures_are_observed_days(self):
        from mom_index.sample_insights import quality_overview
        records=[record(7), record(3,quality='stale'), record(1,'failed','collection_failed'),record(0,'failed','collection_failed')]
        overview=quality_overview(records)
        row=overview['sectors']['gold']
        self.assertEqual(row['last_collection_success_at'], records[1]['provenance']['finished_at'])
        self.assertEqual(row['last_qualified_at'],records[0]['provenance']['finished_at'])
        self.assertEqual(row['consecutive_failed_observations'],2)
        self.assertEqual(overview['observed_dates'],4)

    def test_unverified_mock_and_expired_data_cannot_be_presented_as_current(self):
        from mom_index.sample_insights import quality_overview
        good=record(3)
        mock=record(0); mock['source']='mock'
        legacy=record(0); legacy['provenance']={}
        overview=quality_overview([good,mock,legacy])
        self.assertTrue(overview['expired'])
        self.assertEqual(overview['observed_dates'],1)
        self.assertEqual(overview['current_qualified_count'],0)


if __name__=='__main__':
    unittest.main()
