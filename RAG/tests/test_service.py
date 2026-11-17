"""Service + real provider adapter contracts, using a fake HTTP response only."""
import io
import json
from unittest.mock import Mock
from urllib.error import URLError

from test_core import CorpusFixture
from banking_rag.providers import OllamaClient
from banking_rag.service import RAGService


class Response(io.BytesIO):
    status = 200


class ServiceTests(CorpusFixture):
    def setUp(self):
        super().setUp()
        self.build([("guide", "# 转账确认\n修改转账金额后需要重新确认。\nbalance 表示余额。", {})])
        self.client = OllamaClient()
        self.client._opener = Mock()
        self.service = RAGService(self.index_path, self.client)

    def respond(self, answer, citations):
        body = {"message": {"content": json.dumps({"answer": answer, "citations": citations})}}
        self.client._opener.open.return_value = Response(json.dumps(body).encode())

    def ask(self):
        return self.service.ask("修改转账金额后需要确认吗？", generation_model="test-chat")

    def test_generation_integrates_inline_citations_and_source_metadata(self):
        self.respond("修改金额后需要重新确认。[S1]", ["S1"])
        result = self.ask()
        self.assertEqual(result["status"], "grounded")
        self.assertEqual(result["generation_mode"], "ollama")
        self.assertEqual(result["citations"][0]["document_id"], "guide")
        request = self.client._opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertIn("每个非空段落", payload["messages"][0]["content"])
        self.assertNotIn("tools", payload)
        self.assertEqual(result["tool_calls"], [])

    def test_missing_inline_citation_rejects_generation(self):
        self.respond("未核验的模型文本", ["S1"])
        result = self.ask()
        self.assertEqual(result["status"], "generation_rejected")
        self.assertNotIn("未核验的模型文本", result["answer"])

    def test_unknown_citation_never_exposes_model_text(self):
        self.respond("伪造模型结果[S99]", ["S99"])
        result = self.ask()
        self.assertEqual(result["generation_mode"], "extractive_fallback")
        self.assertNotIn("伪造模型结果", result["answer"])
        self.assertEqual(result["tool_calls"], [])

    def test_uncited_paragraph_rejects_generation(self):
        self.respond("正确引用。[S1]\n\n未引用的额外断言。", ["S1"])
        self.assertEqual(self.ask()["status"], "generation_rejected")

    def test_no_citations_returns_fixed_abstention(self):
        self.respond("未经证实的无引用文本", [])
        result = self.ask()
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["citations"], [])
        self.assertNotIn("未经证实", result["answer"])

    def test_transport_error_falls_back_to_original_text(self):
        self.client._opener.open.side_effect = URLError("PRIVATE ERROR")
        result = self.ask()
        self.assertEqual(result["generation_mode"], "extractive_fallback")
        self.assertIn("修改转账金额后需要重新确认", result["answer"])
        self.assertNotIn("PRIVATE ERROR", json.dumps(result))

    def test_unknown_question_does_not_call_model(self):
        result = self.service.ask("火星矿物光谱", generation_model="test-chat")
        self.assertEqual(result["status"], "no_evidence")
        self.client._opener.open.assert_not_called()

    def test_personal_balance_queries_do_not_call_model(self):
        for question in ("我的账户余额是多少？", "What is my balance?", "Show my account balance"):
            with self.subTest(question=question):
                result = self.service.ask(question, generation_model="test-chat")
                self.assertEqual(result["status"], "needs_business_data")
                self.assertEqual(result["evidence"], [])
        self.client._opener.open.assert_not_called()

    def test_expired_evidence_is_not_sent_to_model(self):
        self.build([("expired", "转账金额需要确认。", {"valid_until": "2026-10-19"})])
        result = RAGService(self.index_path, self.client).ask(
            "转账金额确认", as_of="2026-10-20", generation_model="test-chat")
        self.assertEqual(result["status"], "no_evidence")
        self.client._opener.open.assert_not_called()
