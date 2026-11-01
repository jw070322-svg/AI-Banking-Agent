"""Offline tests for opt-in official-source verification.

No sockets, no model: every test injects `transport` and `model`. The
integration runner patches `first_agent.external_services.request` globally, so
nothing here may depend on the real one.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from first_agent import online_verification as ov


CSRC_URL = 'https://www.csrc.gov.cn/xizang/c105485/c1304209/content.shtml'

PAGE = '''<html><head><title>基金投资者教育手册</title>
<meta name="ArticleTitle" content="《基金投资者教育手册》">
<meta name="PubDate" content="2009-05-07 10:00:00">
<meta name="ContentSource" content="西藏证监局">
<script>var hidden = "基金 不该出现";</script>
<style>.x{color:red}</style>
</head><body>
<p>无障碍浏览 首页 政务信息 专题专栏</p>
<p>基金投资者即基金份额持有人，是基金的出资人，基金资产的所有者和基金投资收益的受益人。</p>
<p>基金管理人是基金产品的募集者和基金的管理者，负责基金资产的投资运作。</p>
<p>与基金无关的另一段说明文字，用于确认选段不会乱抓。</p>
</body></html>'''


class FakeModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def complete(self, system, user, *, max_tokens=400):
        self.calls.append({'system': system, 'user': user, 'max_tokens': max_tokens})
        if self.answer is None:
            return {'status': 'unavailable', 'answer': ''}
        return {'status': 'ok', 'answer': self.answer}


def fake_transport(bodies=None, status='ok'):
    calls = []

    def call(url, payload=None, timeout=None, **kwargs):
        calls.append({'url': url, 'kwargs': kwargs})
        body = (bodies or {}).get(url, PAGE)
        if status != 'ok':
            return {'status': status, 'http_status': 503}
        return {'status': 'ok', 'http_status': 200, 'body': body}
    call.calls = calls
    return call


class ParserTests(unittest.TestCase):
    def test_extracts_title_meta_and_visible_blocks(self):
        parser = ov.VisibleText()
        parser.feed(PAGE)
        parser.close()
        self.assertIn('基金投资者教育手册', parser.title)
        self.assertEqual(parser.meta.get('ContentSource'), '西藏证监局')
        self.assertTrue(any('基金投资者即基金份额持有人' in b for b in parser.blocks))

    def test_script_and_style_are_excluded(self):
        parser = ov.VisibleText()
        parser.feed(PAGE)
        parser.close()
        joined = '\n'.join(parser.blocks)
        self.assertNotIn('color:red', joined)
        self.assertNotIn('不该出现', joined)


class PassageTests(unittest.TestCase):
    def test_prefers_blocks_containing_the_term(self):
        blocks = ['与主题无关的一段话', '基金是指通过发售基金份额募集资金的产品。', '基金管理人负责投资运作基金资产。']
        passages = ov.select_passages(blocks, '基金')
        self.assertTrue(passages)
        self.assertTrue(all('基金' in p['text'] for p in passages))

    def test_caps_at_limit(self):
        blocks = [f'基金第{i}段说明。' for i in range(10)]
        self.assertEqual(len(ov.select_passages(blocks, '基金')), ov.MAX_PASSAGES)

    def test_returns_empty_when_term_absent(self):
        self.assertEqual(ov.select_passages(['完全无关的正文'], '基金'), [])


class DeclaredSourceTests(unittest.TestCase):
    def test_finds_term_and_source(self):
        source = ov.declared_source('基金是怎么运作的')
        self.assertIsNotNone(source)
        self.assertEqual(source['term'], '基金')
        self.assertTrue(source['source_uri'].startswith('https://'))

    def test_unknown_question_returns_none(self):
        self.assertIsNone(ov.declared_source('今天天气怎么样'))

    def test_longer_alias_wins(self):
        source = ov.declared_source('风险等级怎么划分')
        self.assertIsNotNone(source)
        self.assertEqual(source['term'], '风险等级')


class VerifyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        patcher = patch.object(ov, 'EVIDENCE_DIR', self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_verify(self, question, *, transport=None, model=None):
        return ov.verify(question, transport=transport or fake_transport(),
                         model=model or FakeModel('基金投资者是基金的出资人。'))

    def test_verified_returns_meta_excerpt_and_hash(self):
        result = self.run_verify('基金是怎么运作的')
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['term'], '基金')
        citation = result['citations'][0]
        self.assertIn('基金', citation['excerpt'])
        self.assertEqual(citation['publisher'], '西藏证监局')
        self.assertEqual(citation['published_at'], '2009-05-07')
        self.assertTrue(citation['source_uri'].startswith('https://'))
        self.assertEqual(len(citation['document_sha256']), 64)

    def test_rewrite_ok_is_labelled(self):
        result = self.run_verify('基金是怎么运作的')
        self.assertEqual(result['rewrite']['status'], 'ok')
        self.assertEqual(result['rewrite']['label'], '模型改写（非引用原文）')

    def test_rewrite_rejected_when_it_invents_a_number(self):
        result = self.run_verify('基金是怎么运作的', model=FakeModel('基金每年收益率为 9.9%。'))
        self.assertEqual(result['rewrite']['status'], 'rejected')
        self.assertNotIn('text', result['rewrite'])

    def test_rewrite_unavailable_keeps_excerpt(self):
        result = self.run_verify('基金是怎么运作的', model=FakeModel(None))
        self.assertEqual(result['rewrite']['status'], 'unavailable')
        self.assertTrue(result['citations'])

    def test_pdf_source_reports_unparseable_with_link(self):
        transport = fake_transport(bodies={})
        result = self.run_verify('现金流是什么意思', transport=transport)
        self.assertEqual(result['status'], 'source_unparseable')
        self.assertEqual(result['sources'][0]['kind'], 'pdf')
        self.assertTrue(result['sources'][0]['url'].lower().endswith('.pdf'))
        # 绝不去下载 PDF 本体
        self.assertFalse(any(c['url'].lower().endswith('.pdf') for c in transport.calls))

    def test_blocked_host_is_never_fetched(self):
        transport = fake_transport()
        entries = [{'term': '基金', 'aliases': [], 'source_uri': 'https://www.investor.gov/x',
                    'source_title': 'investor.gov', 'definition': 'x'}]
        result = ov.verify('基金是什么', transport=transport, model=FakeModel('x'), entries=entries)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(transport.calls, [])

    def test_transport_failure_reports_unavailable(self):
        result = self.run_verify('基金是怎么运作的', transport=fake_transport(status='unavailable'))
        self.assertEqual(result['status'], 'unavailable')

    def test_page_without_term_is_partial(self):
        body = PAGE.replace('基金', '产品')
        result = self.run_verify('基金是怎么运作的', transport=fake_transport(bodies={CSRC_URL: body}))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['citations'], [])

    def test_private_question_blocked_before_any_fetch(self):
        transport = fake_transport()
        result = ov.verify('我的账户余额是多少', transport=transport, model=FakeModel('x'))
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(transport.calls, [])

    def test_evidence_snapshot_has_no_question_text(self):
        result = self.run_verify('基金是怎么运作的')
        files = list(self.dir.glob('*.json'))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding='utf-8')
        self.assertNotIn('基金是怎么运作的', text)
        self.assertIn('西藏证监局', text)
        # 与返回的哈希一致，且不含提问
        self.assertIn(result['citations'][0]['document_sha256'][:16], files[0].name)


class RewriteGuardTests(unittest.TestCase):
    def test_accepts_sentence_without_new_facts(self):
        verdict = ov.safe_rewrite('基金是集合投资工具。', '基金是集合投资工具，由管理人运作。')
        self.assertEqual(verdict['status'], 'ok')

    def test_rejects_new_number(self):
        verdict = ov.safe_rewrite('基金托管费为 0.25%。', '基金由托管人负责保管资产。')
        self.assertEqual(verdict['status'], 'rejected')

    def test_rejects_url_or_think_block(self):
        self.assertEqual(ov.safe_rewrite('详见 https://x.cn。', '基金是集合投资工具。')['status'], 'rejected')
        self.assertEqual(ov.safe_rewrite('<think>想一下</think>基金是工具。', '基金是集合投资工具。')['status'], 'rejected')

    def test_rejects_too_long_first_sentence(self):
        verdict = ov.safe_rewrite('基' * 150 + '。', '基金是集合投资工具。')
        self.assertEqual(verdict['status'], 'rejected')

    def test_takes_first_sentence_only(self):
        verdict = ov.safe_rewrite('基金是集合投资工具。它还托管在银行。', '基金是集合投资工具。')
        self.assertEqual(verdict['status'], 'ok')
        self.assertEqual(verdict['text'], '基金是集合投资工具。')


class HostAllowlistTests(unittest.TestCase):
    def test_csrc_and_pbc_subdomain_allowed(self):
        from first_agent.external_services import local_request_headers
        for url in ('https://www.csrc.gov.cn/a', 'https://guiyang.pbc.gov.cn/b'):
            local, _ = local_request_headers(url, hosts=ov.EVIDENCE_HOSTS)
            self.assertFalse(local)

    def test_default_profile_still_rejects_official_hosts(self):
        from first_agent.external_services import local_request_headers
        with self.assertRaises(ValueError):
            local_request_headers('https://www.csrc.gov.cn/a')

    def test_non_allowlisted_host_rejected(self):
        from first_agent.external_services import local_request_headers
        with self.assertRaises(ValueError):
            local_request_headers('https://evil.example/a', hosts=ov.EVIDENCE_HOSTS)


class ServiceWiringTests(unittest.TestCase):
    def setUp(self):
        from first_agent.service import AgentService
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.service = AgentService(str(Path(temp.name) / 'db.sqlite3'))
        self.sid = self.service.create_session()
        # 让本地知识库明确"没有证据"，否则不会走到核验/兜底分支。
        from first_agent import finance_lexicon
        for patcher in (
            patch.object(self.service.rag, 'ask', return_value={'status': 'no_evidence', 'citations': [], 'evidence': []}),
            patch.object(finance_lexicon, 'answer', return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_verify_not_called_without_consent(self):
        with patch.object(ov, 'verify') as verify, \
             patch.object(self.service.external, 'generate', return_value={'status': 'ok', 'answer': ''}):
            self.service.research_call(self.sid, 'knowledge', {'question': '基金是怎么运作的'})
            verify.assert_not_called()

    def test_verify_called_with_consent(self):
        fake = {'status': 'verified', 'citations': [{'title': 't', 'source_uri': 'https://www.csrc.gov.cn/x',
                                                     'excerpt': '基金是集合投资工具。'}],
                'rewrite': {'status': 'ok', 'text': '基金是集合投资工具。', 'label': '模型改写（非引用原文）'},
                'term': '基金', 'sources': [], 'steps': []}
        with patch.object(ov, 'verify', return_value=fake) as verify:
            result = self.service.research_call(self.sid, 'knowledge',
                                                {'question': '基金是怎么运作的', 'online_verify': True})
        verify.assert_called_once()
        self.assertEqual(result['data']['status'], 'verified')

    def test_failed_verification_falls_back_and_records_step(self):
        with patch.object(ov, 'verify', return_value={'status': 'no_source', 'detail': 'x',
                                                      'citations': [], 'sources': [], 'steps': []}), \
             patch.object(self.service.external, 'generate', return_value={'status': 'ok', 'answer': ''}):
            result = self.service.research_call(self.sid, 'knowledge',
                                                {'question': '一个知识库没有的问题', 'online_verify': True})
        data = result['data']
        self.assertEqual(data['status'], 'needs_evidence')
        self.assertEqual(data['online_verification']['status'], 'no_source')
        self.assertIn('official_web', [s['provider'] for s in data['fallback_steps']])


if __name__ == '__main__':
    unittest.main()
