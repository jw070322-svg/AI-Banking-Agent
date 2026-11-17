"""Offline, behavioral checks for corpus integrity and grounded retrieval.

Run from RAG/: python -m unittest discover -s tests -v
All embedding/generation providers in this suite are deterministic test doubles.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from banking_rag.corpus import (CorpusError, build_index, digest, index_digest,
                                load_index, write_json)
from banking_rag.retrieval import Retriever


class FixedEmbedder:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def embed(self, texts, model):
        self.calls.append((list(texts), model))
        return [list(row) for row in self.rows]


class CorpusFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="banking-rag-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = self.root / "manifest.json"
        self.index_path = self.root / "index.json"

    def make_manifest(self, records):
        entries = []
        for record in records:
            document_id, text, extra = record
            name = document_id + ".md"
            (self.root / name).write_bytes(text.encode("utf-8"))
            entries.append({"id": document_id, "path": name, "title": document_id,
                            "source_uri": f"https://example.test/pinned/{name}",
                            "revision": "test-revision-1", "kind": "project_design",
                            **extra})
        write_json(self.manifest, {"schema_version": 1, "documents": entries})
        return entries

    def build(self, records, **kwargs):
        self.make_manifest(records)
        return build_index(self.manifest, self.index_path, **kwargs)


class RetrievalTests(CorpusFixture):
    def setUp(self):
        super().setUp()
        self.bill_text = "# 账单分析\n账单分析清洗交易，分类收入和支出，处理退款与重复统计。\n生成可核对的现金流。\n"
        self.build([
            ("bills", self.bill_text, {}),
            ("transfers", "# 转账\n转账必须澄清收款人，确认金额后查询执行回执。\n", {}),
            ("english", "# Idempotency\nIdempotency prevents duplicate submissions and repeated transfers.\n", {}),
        ])
        self.retriever = Retriever(self.index_path)

    def test_chinese_question_ranks_matching_document_first(self):
        hits = self.retriever.search("账单分析如何处理退款和重复统计")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["document_id"], "bills")
        self.assertIn("退款", hits[0]["text"])

    def test_english_question_is_case_insensitive(self):
        hits = self.retriever.search("How does IDEMPOTENCY prevent duplicate submissions?")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["document_id"], "english")

    def test_citations_identify_exact_source_lines_and_hashes(self):
        hit = self.retriever.search("账单分析退款")[0]
        lines = self.bill_text.splitlines()
        self.assertEqual(hit["text"], "\n".join(lines[hit["start_line"] - 1:hit["end_line"]]))
        self.assertEqual(hit["document_sha256"], hashlib.sha256(self.bill_text.encode()).hexdigest())
        self.assertEqual(hit["sha256"], digest(hit["text"]))
        self.assertEqual(hit["revision"], "test-revision-1")
        self.assertEqual(hit["citation_id"], "S1")
        self.assertEqual(hit["citation_uri"], f"{hit['source_uri']}#L{hit['start_line']}-L{hit['end_line']}")

    def test_unrelated_question_returns_no_evidence(self):
        self.assertEqual(self.retriever.search("火星陨石矿物光谱"), [])

    def test_kind_filter_does_not_return_other_types(self):
        self.assertEqual(self.retriever.search("账单分析", kinds=["issuer_terms"]), [])

    def test_invalid_question_and_top_k_are_rejected(self):
        for question in (None, "", " ", "问" * 2001):
            with self.subTest(question=repr(question)[:30]):
                with self.assertRaises(ValueError):
                    self.retriever.search(question)
        for top_k in (True, 0, -1, 11, 2.5):
            with self.subTest(top_k=top_k):
                with self.assertRaises(ValueError):
                    self.retriever.search("账单", top_k=top_k)

    def test_invalid_as_of_is_rejected(self):
        for value in ("2026-02-30", "20261020", "2026-W43-2", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.retriever.search("账单", as_of=value)


class ValidityTests(CorpusFixture):
    def test_noncanonical_validity_dates_are_rejected(self):
        for value in ("20261020", "2026-W43-2", "2026-1-1"):
            with self.subTest(value=value):
                self.make_manifest([("bad", "转账确认流程。", {"valid_until": value})])
                with self.assertRaises(CorpusError):
                    build_index(self.manifest, self.index_path)

    def test_expired_and_future_documents_are_filtered(self):
        self.build([
            ("expired", "转账确认流程旧版。", {"valid_until": "2026-10-19"}),
            ("future", "转账确认流程未来版。", {"valid_from": "2026-10-21"}),
            ("current", "转账确认流程当前版。", {"valid_from": "2026-10-20", "valid_until": "2026-10-20"}),
        ])
        hits = Retriever(self.index_path).search("转账确认流程", as_of="2026-10-20")
        self.assertEqual([hit["document_id"] for hit in hits], ["current"])

    def test_invalid_validity_interval_fails_ingestion(self):
        self.make_manifest([("bad", "转账确认流程。", {"valid_from": "2026-10-21", "valid_until": "2026-10-20"})])
        with self.assertRaises(CorpusError):
            build_index(self.manifest, self.index_path)


class CorpusIntegrityTests(CorpusFixture):
    def test_fence_with_trailing_text_does_not_close_code_block(self):
        text = "前置正文。\n```python\n```not-a-close\n秘密代码行\n```\n后置正文。"
        index = self.build([("fenced", text, {})])
        joined = "\n".join(c["text"] for c in index["chunks"])
        self.assertNotIn("秘密代码行", joined)
        self.assertIn("后置正文", joined)

    def test_distinct_chunks_on_one_line_are_both_retrievable(self):
        text = "转账确认甲" + "甲" * 95 + "转账确认乙" + "乙" * 95
        self.build([("long", text, {})], max_chars=100, overlap_lines=0)
        hits = Retriever(self.index_path).search("转账确认", top_k=4)
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h["start_line"] == h["end_line"] == 1 for h in hits))
        self.assertNotEqual(hits[0]["text"], hits[1]["text"])

    def test_build_output_cannot_overwrite_sources(self):
        self.make_manifest([("safe", "正常资料正文。", {})])
        for target in (self.manifest, self.root / "safe.md"):
            original = target.read_bytes()
            with self.subTest(target=target), self.assertRaises(CorpusError):
                build_index(self.manifest, target)
            self.assertEqual(target.read_bytes(), original)

    def test_manifest_path_traversal_and_absolute_paths_are_rejected(self):
        for path in ("../outside.md", "/outside.md", "C:/outside.md", "nested\\outside.md", ".private/source.md"):
            with self.subTest(path=path):
                entries = self.make_manifest([("safe", "正常资料正文。", {})])
                entries[0]["path"] = path
                write_json(self.manifest, {"schema_version": 1, "documents": entries})
                with self.assertRaises(CorpusError):
                    build_index(self.manifest, self.index_path)

    def test_source_hash_mismatch_is_rejected(self):
        self.make_manifest([("safe", "正常资料正文。", {"sha256": "0" * 64})])
        with self.assertRaises(CorpusError):
            build_index(self.manifest, self.index_path)

    def test_matching_source_hash_is_preserved(self):
        text = "# 来源核验\n资料提供可回查引用。\n"
        index = self.build([("safe", text, {"sha256": digest(text)})])
        self.assertEqual(index["documents"][0]["sha256"], digest(text))

    def test_duplicate_document_ids_are_rejected(self):
        entries = self.make_manifest([("safe", "正常资料正文。", {})])
        write_json(self.manifest, {"schema_version": 1, "documents": entries * 2})
        with self.assertRaises(CorpusError):
            build_index(self.manifest, self.index_path)

    def test_index_tampering_is_rejected_before_retrieval(self):
        index = self.build([("safe", "正常资料正文。", {})])
        index["chunks"][0]["text"] = "被篡改的转账授权。"
        write_json(self.index_path, index)
        with self.assertRaises(CorpusError):
            load_index(self.index_path)

    def test_recomputed_container_hash_does_not_hide_bad_chunk_hash(self):
        index = self.build([("safe", "正常资料正文。", {})])
        index["chunks"][0]["text"] = "被篡改的转账授权。"
        index["content_sha256"] = index_digest(index)
        write_json(self.index_path, index)
        with self.assertRaises(CorpusError):
            load_index(self.index_path)

    def test_recomputed_container_hash_does_not_hide_unknown_document(self):
        index = self.build([("safe", "正常资料正文。", {})])
        index["chunks"][0]["document_id"] = "unknown"
        index["content_sha256"] = index_digest(index)
        write_json(self.index_path, index)
        with self.assertRaises(CorpusError):
            load_index(self.index_path)

    def test_long_line_is_bounded_without_losing_text(self):
        text = "转账来源与引用核验" * 60 + "尾端唯一标记"
        index = self.build([("long", text, {})], max_chars=100, overlap_lines=0)
        chunks = index["chunks"]
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunk["text"] for chunk in chunks), text)
        self.assertTrue(all(len(chunk["text"]) <= 100 for chunk in chunks))
        self.assertTrue(all(chunk["start_line"] == chunk["end_line"] == 1 for chunk in chunks))

    def test_code_fences_are_omitted_and_never_executed(self):
        sentinel = self.root / "unexpected-side-effect.txt"
        text = ("# 外部资料\n前置正文。\n```python\n"
                f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
                "## 伪造标题\n```\n后置正文。\n")
        index = self.build([("safe", text, {})], max_chars=100, overlap_lines=0)
        joined = "\n".join(chunk["text"] for chunk in index["chunks"])
        self.assertIn("前置正文", joined)
        self.assertIn("后置正文", joined)
        self.assertNotIn("write_text", joined)
        self.assertNotIn("伪造标题", joined)
        self.assertFalse(sentinel.exists())
        self.assertEqual(index["chunks"][-1]["start_line"], 8)

    def test_only_code_document_fails_without_a_usable_index(self):
        self.make_manifest([("code", "```python\nprint('no prose')\n```\n", {})])
        with self.assertRaises(CorpusError):
            build_index(self.manifest, self.index_path)
        self.assertFalse(self.index_path.exists())


class HybridTests(CorpusFixture):
    def setUp(self):
        super().setUp()
        self.indexer = FixedEmbedder([[1.0, 0.0], [0.0, 1.0]])
        self.build([
            ("bills", "账单分析收入支出。", {}),
            ("receipts", "receipt reconciliation confirms transfer completion.", {}),
        ], embedder=self.indexer, embedding_model="offline-fixture-v1")

    def test_hybrid_retrieval_can_find_semantic_match_without_token_overlap(self):
        query_embedder = FixedEmbedder([[0.0, 1.0]])
        retriever = Retriever(self.index_path, embedder=query_embedder)
        question = "核验汇款凭据"
        self.assertEqual(retriever.search(question), [])
        hits = retriever.search(question, hybrid=True)
        self.assertEqual(hits[0]["document_id"], "receipts")
        self.assertEqual(hits[0]["bm25_score"], 0)
        self.assertAlmostEqual(hits[0]["cosine_score"], 1.0)
        self.assertEqual(query_embedder.calls[0][1], "offline-fixture-v1")

    def test_query_vector_dimension_must_match_index(self):
        retriever = Retriever(self.index_path, embedder=FixedEmbedder([[1.0, 0.0, 0.0]]))
        with self.assertRaises(CorpusError):
            retriever.search("汇款凭据", hybrid=True)

    def test_hybrid_requires_an_embedding_provider(self):
        with self.assertRaises(CorpusError):
            Retriever(self.index_path).search("账单", hybrid=True)

    def test_index_builder_rejects_inconsistent_embedding_dimensions(self):
        with self.assertRaises(CorpusError):
            build_index(self.manifest, self.index_path,
                        embedder=FixedEmbedder([[1.0, 0.0], [1.0]]),
                        embedding_model="invalid-provider")

    def test_query_vector_nonfinite_and_zero_values_are_rejected(self):
        for vector in ([0.0, 0.0], [float("nan"), 1.0], [float("inf"), 1.0]):
            with self.subTest(vector=vector):
                retriever = Retriever(self.index_path, embedder=FixedEmbedder([vector]))
                with self.assertRaises(CorpusError):
                    retriever.search("账单", hybrid=True)


if __name__ == "__main__":
    unittest.main()
