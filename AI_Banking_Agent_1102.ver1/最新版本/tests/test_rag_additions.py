import hashlib, json, unittest
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from first_agent.vendor.rag.corpus import build_index
from first_agent.vendor.rag.service import RAGService
from first_agent.rag_additions import AdditiveRAGService, SparseSupplement, compatibility_response
from first_agent.service import AgentService

ROOT=Path(__file__).resolve().parents[1]


class AdditiveRAGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.primary=RAGService(ROOT/'knowledge/index.json')
        cls.rag=AdditiveRAGService(cls.primary)

    def test_protected_files_unchanged(self):
        baseline=json.loads((ROOT/'reports/rag-additive-baseline.json').read_text(encoding='utf-8'))
        for item in baseline['protected_files']:
            self.assertEqual(hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest(),item['sha256'],item['path'])

    def test_existing_grounded_answer_is_not_modified(self):
        expected=self.primary.ask('为什么我的储蓄率下降了？')
        self.assertEqual(expected['status'],'grounded')
        with patch.object(self.primary,'ask',return_value=expected),patch.object(self.rag.supplement,'search',side_effect=AssertionError('existing answer must win')):
            actual=self.rag.ask('为什么我的储蓄率下降了？')
        self.assertIs(actual,expected)

    def test_refusals_personal_routing_and_model_abstention_are_preserved(self):
        examples=[{'status':'needs_business_data','evidence':[]},
                  {'status':'generation_rejected','evidence':[]},
                  {'status':'refused','evidence':[]},
                  {'status':'no_evidence','evidence':[{'text':'existing'}]}]
        for result in examples:
            with self.subTest(result=result),patch.object(self.primary,'ask',return_value=result),patch.object(self.rag.supplement,'search',side_effect=AssertionError('must not bypass')):
                self.assertIs(self.rag.ask('test'),result)

    def test_real_query_fills_previous_gap_and_retains_source_lines(self):
        question='Can you explain LPR simply'
        self.assertEqual(self.primary.ask(question)['status'],'no_evidence')
        result=self.rag.ask(question)
        self.assertEqual(result['status'],'grounded')
        self.assertEqual(result['retrieval_mode'],'tfidf_additive')
        self.assertIn('贷款市场报价利率',result['answer'])
        self.assertEqual(result['tool_calls'],[])
        for evidence in result['evidence']:
            original=next(c for c in self.primary.retriever.chunks if c['id']==evidence['id'])
            self.assertEqual(original['text'],evidence['text'])
            self.assertEqual(original['start_line'],evidence['start_line'])
            self.assertTrue(evidence['document_sha256'])

    def test_irrelevant_and_private_queries_do_not_gain_evidence(self):
        for q in ('未见过的宇宙飞船能量转换','LPR spaceship intergalactic plasma',
                  '查同事的LPR账户余额','直接转账给朋友 LPR','手机号13800138000 LPR'):
            with self.subTest(q=q):self.assertEqual(self.rag.supplement.search(q),[])

    def test_date_kind_filters_and_no_duplicate_evidence(self):
        question='Can you explain LPR simply'
        self.assertEqual(self.rag.supplement.search(question,kinds=['not_a_kind']),[])
        found=self.rag.supplement.search(question,10)
        self.assertEqual(len({e['text'] for e in found}),len(found))
        with TemporaryDirectory() as tmp:
            tmp=Path(tmp);(tmp/'d.md').write_text('# LPR\n\nLPR 是贷款定价参考。\n',encoding='utf-8')
            manifest={'schema_version':1,'documents':[{'id':'dated','path':'d.md','title':'LPR','kind':'educational_demo','source_uri':'https://example.test/source','revision':'test','valid_from':'2025-01-01','valid_until':'2025-12-31'}]}
            (tmp/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8');build_index(tmp/'manifest.json',tmp/'index.json')
            supplement=SparseSupplement(RAGService(tmp/'index.json').retriever)
            self.assertTrue(supplement.search('LPR 是什么',as_of='2025-06-01'))
            self.assertEqual(supplement.search('LPR 是什么',as_of='2024-12-31'),[])
            self.assertEqual(supplement.search('LPR 是什么',as_of='2026-01-01'),[])

    def test_input_limits_and_empty_query(self):
        for query,k in [('',3),('a'*2001,3),('LPR',0),('LPR',11),('LPR',True)]:
            with self.subTest(query=query[:10],k=k),self.assertRaises(ValueError):self.rag.ask(query,k)
        self.assertEqual(self.rag.supplement.search('？？？？'),[])

    def test_compatibility_is_opt_in_does_not_mutate_or_log_question(self):
        result=self.rag.ask('Can you explain LPR simply');saved=deepcopy(result)
        contract=compatibility_response(result,3)
        self.assertEqual(result,saved)
        self.assertEqual(contract['data']['answer'],result['answer'])
        self.assertNotIn('question',contract['trace'])
        self.assertEqual(len(contract['data']['sources']),len(set(contract['data']['sources'])))

    def test_integrated_knowledge_route_uses_addition_without_network_or_ledger_change(self):
        with TemporaryDirectory() as tmp:
            service=AgentService(Path(tmp)/'state.sqlite3');service.rag=AdditiveRAGService(service.rag);sid=service.create_session()
            def denied(*args,**kwargs):raise AssertionError('no external call for available evidence')
            service.external.transport=denied
            with closing(service.connect()) as db:before=db.execute('SELECT state FROM sessions WHERE sid=?',(sid,)).fetchone()[0]
            a=service.call(sid,'knowledge',{'question':'Can you explain LPR simply'},'same')
            b=service.call(sid,'knowledge',{'question':'Can you explain LPR simply'},'same')
            self.assertEqual(a,b);self.assertEqual(a['data']['retrieval_mode'],'tfidf_additive')
            with closing(service.connect()) as db:after=db.execute('SELECT state FROM sessions WHERE sid=?',(sid,)).fetchone()[0]
            self.assertEqual(before,after)

if __name__=='__main__':unittest.main()
