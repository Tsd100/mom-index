"""合成语言回归用例；不是人工标注的真实帖子评测集。"""
import copy
import json
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch, Mock
from pathlib import Path

from mom_index.analyzer.llm_analyzer import analyze_post
from mom_index.provenance import now_local


class LanguageTests(unittest.TestCase):
    def test_denied_actions_are_not_trades(self):
        for text in ['不要买入，别再加仓了', '我不想割肉，也不会清仓', '不买了', '暂时不卖了']:
            with self.subTest(text=text):
                self.assertEqual(analyze_post({'title': text}, 'gold').intent, 'neutral')

    def test_question_quote_and_losses_are_not_executed_intent(self):
        for text in ['现在可以买入吗？', '要不要割肉', '朋友说买入，我还在观望',
                     '有人喊“满仓梭哈”，我继续观望', '亏麻了，已经深套了']:
            with self.subTest(text=text):
                self.assertEqual(analyze_post({'title': text}, 'gold').intent, 'neutral')

    def test_explicit_actions_survive_other_denied_clauses(self):
        for text, intent in [('今天已买入', 'buy'), ('我已经清仓了', 'sell'),
                             ('不要追高，但我已经卖了', 'sell'),
                             ('朋友说减仓，但我今天加仓了', 'buy'),
                             ('我不想卖，今天买入了', 'buy')]:
            with self.subTest(text=text):
                self.assertEqual(analyze_post({'title': text}, 'gold').intent, intent)

    def test_reported_speaker_continues_across_comma_and_long_negation(self):
        for text in ['朋友说，今天已经清仓了', '朋友已经买入了，我还在观望',
                     '我朋友今天买入了，我还在观望',
                     '我不认为现在这个价格适合继续买入', '并没有在下跌之后选择补仓']:
            with self.subTest(text=text):
                self.assertEqual(analyze_post({'title': text}, 'gold').intent, 'neutral')
        self.assertEqual(analyze_post({'title': '朋友说，今天买入，但我已经清仓了'}, 'gold').intent, 'sell')

    def test_reported_question_cannot_change_previous_author_statement(self):
        self.assertEqual(analyze_post({'title': '我买入了。朋友说现在卖出？'}, 'gold').intent, 'buy')
        self.assertEqual(analyze_post({'title': '我买入了，朋友说现在卖出？'}, 'gold').intent, 'buy')

    def test_optional_model_cannot_override_expression_or_publish_trade_advice(self):
        from mom_index.analyzer.llm_analyzer import llm_rejudge
        post = {'title': '亏麻了，已经深套了'}
        result = analyze_post(post, 'gold')
        response = Mock()
        response.json.return_value = {'choices': [{'message': {'content':
            '{"newbie_score":45,"intent":"sell","sentiment":1,"reasoning":"应大幅减仓"}'}}]}
        with patch('requests.post', return_value=response), patch('mom_index.analyzer.llm_analyzer._llm_used', 0):
            checked = llm_rejudge(post, result)
        self.assertEqual(checked.newbie_score, 45)
        self.assertEqual(checked.intent, 'neutral')
        self.assertLess(checked.sentiment_score, 0)
        self.assertIn('未确认方向', checked.intent_basis)
        self.assertNotIn('减仓', checked.reasoning)

    def test_denied_optimism_does_not_become_greed(self):
        for text in ['不是稳赚，别信必涨', '并非稳赚，也不会暴涨', '有人说“稳赚必涨”，我不认同']:
            with self.subTest(text=text):
                self.assertEqual(analyze_post({'title': text}, 'gold').sentiment_score, 0)
        self.assertLess(analyze_post({'title': '亏麻了，已经深套了'}, 'gold').sentiment_score, 0)
        self.assertGreater(analyze_post({'title': '满仓梭哈，等着起飞'}, 'gold').sentiment_score, 0)


def summary_fixture():
    today = now_local().date()
    day = today.isoformat()
    previous = (today - timedelta(days=3)).isoformat()
    return {'latest': {'date': day, 'provenance': {'finished_at': now_local().isoformat()},
                      'sectors': {'gold': {'index': 45, 'definition_id': 'same',
                          'quality': {'status': 'ok', 'valid_count': 48, 'sample_count': 60},
                          'top_newbie_posts': [{'title': '今天加仓了', 'source_url': 'https://guba.eastmoney.com/news,1.html',
                                                'reasoning': '命中加仓'}]}}},
            'real_dates': [previous, day],
            'sector_history': {'gold': [{'date': previous, 'index': 30, 'definition_id': 'same'},
                                       {'date': day, 'index': 45, 'definition_id': 'same'}]}}


class SummaryTests(unittest.TestCase):
    def summary(self, data):
        from mom_index.daily_summary import build_daily_summary
        return build_daily_summary(data)

    def test_summary_has_actual_comparison_date_counts_and_evidence(self):
        data = summary_fixture()
        result = self.summary(data)
        item = result['highlights'][0]
        self.assertEqual(item['delta'], 15)
        self.assertEqual(item['comparison_date'], data['real_dates'][0])
        self.assertEqual(item['valid_count'], 48)
        self.assertEqual(item['evidence'][0]['title'], '今天加仓了')
        self.assertEqual(result['available_count'], 1)

    def test_definition_change_or_quality_gap_prevents_comparison(self):
        for change in ['definition', 'gap', 'missing_definition']:
            with self.subTest(change=change):
                data = summary_fixture()
                history = data['sector_history']['gold']
                if change == 'definition':
                    history[0]['definition_id'] = 'old'
                elif change == 'missing_definition':
                    data['latest']['sectors']['gold'].pop('definition_id')
                else:
                    history.insert(1, {'date': (now_local().date()-timedelta(days=1)).isoformat(),
                                       'index': None, 'definition_id': 'same'})
                self.assertEqual(self.summary(data)['highlights'], [])
                self.assertEqual(len(self.summary(data)['not_comparable']), 1)

    def test_stale_and_bad_quality_cannot_produce_highlights(self):
        data = summary_fixture()
        data['latest']['provenance']['finished_at'] = '2020-01-01T17:00:00+08:00'
        self.assertEqual(self.summary(data)['highlights'], [])
        self.assertEqual(self.summary(data)['available_count'], 0)
        data = summary_fixture()
        data['latest']['sectors']['gold']['quality'] = {'status': 'collection_failed', 'reasons': ['来源失败']}
        result = self.summary(data)
        self.assertEqual(result['unavailable'][0]['reason'], '来源失败')
        self.assertEqual(result['highlights'], [])

    def test_summary_is_pure_and_missing_latest_is_explicit(self):
        data = summary_fixture()
        before = copy.deepcopy(data)
        self.summary(data)
        self.assertEqual(data, before)
        self.assertEqual(self.summary({})['status'], 'waiting')

    def test_dashboard_publication_adds_summary_without_rewriting_history(self):
        from mom_index.analyzer import index_calculator as calc
        data = summary_fixture()
        record = data['latest']
        record['source'] = 'real'
        record['provenance'].update(schema_version=2, mock_excluded=True, run_id='test',
            definition={'id': 'same', 'sectors': {'gold': {'code':'of518880', 'etf':'518880'}}})
        record['sectors']['gold']['interpretation'] = '建议大幅减仓'
        with tempfile.TemporaryDirectory() as directory, patch.object(calc, 'DATA_DIR', directory):
            path = Path(directory, 'production', 'history.json')
            path.parent.mkdir()
            path.write_text(json.dumps({'records': [record]}, ensure_ascii=False), encoding='utf-8')
            before = path.read_bytes()
            dashboard = calc.get_dashboard_data()
            self.assertEqual(dashboard['daily_summary']['available_count'], 1)
            self.assertEqual(dashboard['daily_summary']['highlights'], [])
            self.assertNotIn('减仓', dashboard['latest']['sectors']['gold']['interpretation'])
            self.assertEqual(path.read_bytes(), before)


class InterpretationTests(unittest.TestCase):
    def test_interpretations_describe_observation_without_trade_instructions(self):
        from mom_index.analyzer.index_calculator import interpret_index
        from mom_index.analyzer.signal import generate_signals
        for index in [0, 30, 50, 65, 90]:
            data = summary_fixture()
            data['latest']['sectors']['gold']['index'] = index
            text = interpret_index(index) + generate_signals(data)[0]['action']
            for prohibited in ['减仓', '市场底部', '历史级', '原策略', '左侧', '避免追高', '不追高']:
                self.assertNotIn(prohibited, text)


if __name__ == '__main__':
    unittest.main()
