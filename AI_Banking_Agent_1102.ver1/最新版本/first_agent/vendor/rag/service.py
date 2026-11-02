"""Retrieval, extractive baseline, optional local generation, citation checks."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from .retrieval import Retriever, tokenize


class RAGService:
    def __init__(self, index_path, client=None):
        self.retriever = Retriever(index_path, embedder=client)
        self.client = client

    def search(self, question: str, top_k: int = 4, **kwargs) -> list[dict]:
        return self.retriever.search(question, top_k, **kwargs)

    def ask(self, question: str, top_k: int = 4, *, as_of: str | None = None,
            kinds: list[str] | None = None, hybrid: bool = False,
            generation_model: str | None = None) -> dict:
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError("问题需要 1–2000 个字符")
        if type(top_k) is not int or not 1 <= top_k <= 10:
            raise ValueError("top_k 必须为 1–10")
        base = {"schema_version": 1, "question": question,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "index_sha256": self.retriever.index["content_sha256"],
                "retrieval_mode": "hybrid" if hybrid else "bm25",
                "generation_mode": "ollama" if generation_model else "extractive",
                "status": "no_evidence", "answer": "知识库未找到足够依据。请补充资料或将问题交给对应业务工具。",
                "citations": [], "evidence": [], "warnings": [], "tool_calls": []}
        # This is a routing convenience, not an authorization or privacy boundary.
        personal = re.search(r"(我的|我现在|我账户|本人|银行卡里|my\s+(account|balance)).{0,20}(余额|流水|账单|到账|交易|balance)|我.{0,8}(还有|剩余).{0,8}(钱|余额)", question, re.I)
        personal = personal or re.search(
            r"\bmy\s+(?:(?:bank|account|available|current)\s+)*(?:balance|transactions?|statement)\b",
            question, re.I)
        if personal and not re.search(r"如何|怎么|口径|流程|设计|实现", question):
            base.update(status="needs_business_data", answer="此问题需要已授权业务接口的实时账户或交易数据，项目资料不能提供你的实际余额或交易结果。")
            return base
        evidence = self.search(question, top_k, as_of=as_of, kinds=kinds, hybrid=hybrid)
        base["evidence"] = evidence
        if not evidence:
            return base
        if any(e["kind"] == "project_design" for e in evidence):
            base["warnings"].append("引用包含项目设计资料，不能证明相关功能已实现，也不代表真实银行条款或现行法规。")
        if any(not e.get("valid_until") for e in evidence):
            base["warnings"].append("部分资料未提供有效期；固定版本可追溯，但当前业务适用性仍需核验。")
        if generation_model:
            if self.client is None:
                raise ValueError("生成模式需要本地模型 client")
            from .providers import ProviderError
            payload = [{"id": e["citation_id"], "text": e["text"], "source": e["citation_uri"],
                        "title": e["title"], "heading": e["section"], "updated_at": e["revision"]}
                       for e in evidence]
            try:
                result = self.client.generate(question, payload, generation_model)
            except ProviderError:
                base["warnings"].append("本地生成服务不可用或输出结构错误，已降级为原文摘录。")
                base["generation_mode"] = "extractive_fallback"
            else:
                allowed = {e["citation_id"] for e in evidence}
                answer = result.get("answer") if isinstance(result, dict) else None
                ids = result.get("citations") if isinstance(result, dict) else None
                markers = set(re.findall(r"\[(S\d+)\]", answer)) if isinstance(answer, str) else set()
                if isinstance(answer, str) and answer.strip() and ids == [] and not markers:
                    base["warnings"].append("模型判定给定证据不足，未转发无引用的生成文本。")
                    return base
                # Every nonempty paragraph must explicitly cite a retrieved passage.
                paragraphs_valid = (isinstance(answer, str) and all(
                    re.search(r"\[S\d+\]", p) for p in answer.split("\n\n") if p.strip()))
                if (not isinstance(answer, str) or not answer.strip() or not isinstance(ids, list)
                    or not ids or any(not isinstance(c, str) for c in ids)
                    or not set(ids).issubset(allowed) or markers != set(ids) or not paragraphs_valid):
                    base.update(status="generation_rejected", answer="生成结果的引用校验未通过。请查看原始证据，或改用离线摘录模式。")
                    base["warnings"].append("引用校验失败；未返回模型的未核验回答。")
                    return base
                base.update(status="grounded", answer=answer)
                base["citations"] = [self._citation(e) for e in evidence if e["citation_id"] in ids]
                base["warnings"].append("引用标识与来源已校验；此校验不等同于逐条事实蕴含验证。")
                return base
        query = set(tokenize(question))
        lines, used = [], []
        for e in evidence:
            candidates = [(i, line) for i, line in enumerate(e["text"].splitlines())
                          if line.strip() and not re.match(r"^\s*(#|[-|\s:]+$)", line)]
            if not candidates:
                continue
            # Select original lines, never invent connective factual claims.
            ordered = sorted(candidates, key=lambda pair: (-len(query & set(tokenize(pair[1]))), pair[0]))
            selected = sorted(ordered[:2])
            excerpt = "\n".join(line for _, line in selected)
            if len(excerpt) > 650:
                excerpt = excerpt[:650] + "…"
            lines.append(f"[{e['citation_id']}] {e['section'] or e['title']}\n{excerpt}")
            used.append(e)
        if not lines:
            return base
        base.update(status="grounded", answer="以下为检索到的原文摘录：\n\n" + "\n\n".join(lines))
        base["citations"] = [self._citation(e) for e in used]
        return base

    @staticmethod
    def _citation(e):
        return {key: e[key] for key in ("citation_id", "document_id", "title", "section", "source_uri",
                                        "citation_uri", "revision", "document_sha256", "start_line", "end_line", "kind")}
