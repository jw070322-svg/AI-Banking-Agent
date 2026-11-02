import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from first_agent.finance_lexicon import answer, entries
from first_agent.service import AgentService

class FinanceGlossaryTests(unittest.TestCase):
    def test_all_canonical_terms_have_correct_direct_definition_and_source(self):
        for item in entries():
            for q in ('什么是'+item['term']+'？',item['term']+'是什么？'):
                with self.subTest(question=q):
                    r=answer(q)
                    self.assertEqual(r['matched_terms'],[item['term']])
                    self.assertIn(item['definition'],r['answer'])
                    self.assertTrue(r['citations'][0]['source_uri'].startswith('https://'))
    def test_alias_comparison_and_no_substring_false_answer(self):
        for q,expected in [('什么是Sharpe ratio',['夏普率']),('借记卡和信用卡的区别',['借记卡','信用卡']),
                           ('基金净值估算是什么',['基金估值']),('复利的公式是什么',['复利']),('复利是什么意思',['复利'])]:
            with self.subTest(question=q):self.assertEqual(set(answer(q)['matched_terms']),set(expected))
        for q in ('什么是可转债','给小王转账500元','今天基金收益率是多少','我的账户余额是多少'):
            with self.subTest(question=q):self.assertIsNone(answer(q))
    def test_assistant_and_knowledge_api_have_same_grounded_answer_without_network(self):
        with TemporaryDirectory() as tmp:
            service=AgentService(Path(tmp)/'demo.sqlite3');sid=service.create_session()
            def denied(*args,**kwargs):raise AssertionError('应直接使用本地知识')
            service.external.transport=denied
            query='什么是债券基金？'
            via_api=service.call(sid,'knowledge',{'question':query},'k')['data']
            via_assistant=service.call(sid,'rpc',{'method':'assistant','args':[query]},'a')['data']
            self.assertEqual(via_api['matched_terms'],['债券基金'])
            self.assertEqual(via_assistant['route'],'customer-result')
            self.assertEqual(via_assistant['results'][0]['result']['answer'],via_api['answer'])
            self.assertTrue(via_api['citations'])

if __name__=='__main__':unittest.main()
