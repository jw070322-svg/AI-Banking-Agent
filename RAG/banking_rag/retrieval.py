"""Chinese/English BM25 and optional cosine + reciprocal rank fusion."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
import re
import unicodedata

from .corpus import CorpusError, load_index, validate_date, validate_vectors

STOP = {"the", "a", "an", "is", "are", "to", "of", "and", "in", "how", "what", "for", "does"}
ZH_STOP = re.compile("请问|请帮我|请解释|告诉我|是什么|怎么|如何|为什么|有哪些|哪些|是否|可以|需要|多少|根据|这个|那个|我们|你们")


def tokenize(text: str) -> list[str]:
    text = ZH_STOP.sub(" ", unicodedata.normalize("NFKC", text).lower())
    tokens = []
    for part in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text):
        if "\u3400" <= part[0] <= "\u9fff":
            tokens.extend(part[i:i + 2] for i in range(len(part) - 1))
            if len(part) == 1:
                tokens.append(part)
        elif part not in STOP:
            tokens.append(part)
    return tokens


def cosine(left, right):
    if len(left) != len(right):
        raise CorpusError("查询与索引向量维度不同，请用相同模型重建索引")
    # Stable normalization avoids overflow when validating arbitrary providers.
    def unit(v):
        scale = max(abs(x) for x in v)
        scaled = [x / scale for x in v]
        norm = math.sqrt(sum(x * x for x in scaled))
        return [x / norm for x in scaled]
    return sum(a * b for a, b in zip(unit(left), unit(right)))


class Retriever:
    def __init__(self, index_path, embedder=None):
        self.index = load_index(index_path)
        self.documents = {d["id"]: d for d in self.index["documents"]}
        self.chunks = self.index["chunks"]
        self.embedder = embedder
        self.counts = [Counter(tokenize(c["section"] + "\n" + c["text"])) for c in self.chunks]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average = sum(self.lengths) / len(self.lengths) or 1
        self.df = Counter(t for c in self.counts for t in c)

    def search(self, question: str, top_k: int = 4, *, as_of: str | None = None,
               kinds: list[str] | None = None, hybrid: bool = False) -> list[dict]:
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError("问题需要 1–2000 个字符")
        if type(top_k) is not int or not 1 <= top_k <= 10:
            raise ValueError("top_k 必须为 1–10")
        today = (datetime.now(timezone(timedelta(hours=8))).date().isoformat()
                 if as_of is None else validate_date(as_of))
        query = set(tokenize(question))
        if not query:
            return []
        eligible = []
        for i, c in enumerate(self.chunks):
            d = self.documents[c["document_id"]]
            if d.get("valid_from") and d["valid_from"] > today:
                continue
            if d.get("valid_until") and d["valid_until"] < today:
                continue
            if kinds is not None and d["kind"] not in kinds:
                continue
            eligible.append(i)
        bm25, coverage = {}, {}
        for i in eligible:
            counts = self.counts[i]
            overlap = query & counts.keys()
            coverage[i] = len(overlap) / len(query)
            score = 0.0
            for t in overlap:
                idf = math.log(1 + (len(self.chunks) - self.df[t] + .5) / (self.df[t] + .5))
                tf = counts[t]
                score += idf * tf * 2.5 / (tf + 1.5 * (.25 + .75 * self.lengths[i] / self.average))
            # A minimum overlap suppresses accidental single-word matches on long queries.
            if overlap and coverage[i] >= .15 and (len(query) <= 3 or len(overlap) >= 2):
                bm25[i] = score
        dense = {}
        if hybrid:
            model = self.index.get("embedding_model")
            if not model or self.embedder is None:
                raise CorpusError("混合检索需要带向量的索引和本地嵌入服务")
            vectors = self.embedder.embed([question], model)
            validate_vectors(vectors, 1)
            for i in eligible:
                value = cosine(vectors[0], self.index["vectors"][i])
                if value >= .65:
                    dense[i] = value
        if hybrid:
            scores = Counter()
            for source in (bm25, dense):
                for rank, i in enumerate(sorted(source, key=lambda j: (-source[j], self.chunks[j]["id"])), 1):
                    scores[i] += 1 / (60 + rank)
        else:
            scores = bm25
        ranked = sorted(scores, key=lambda i: (-scores[i], self.chunks[i]["id"]))
        results, selected = [], []
        for i in ranked:
            c = self.chunks[i]
            # A long source line can contain several distinct chunks. Only remove
            # fully duplicated text, never discard evidence merely for sharing a line.
            if any(c["document_id"] == p["document_id"]
                   and (c["text"] in p["text"] or p["text"] in c["text"])
                   for p in selected):
                continue
            d = self.documents[c["document_id"]]
            source = d["source_uri"]
            results.append({**c, "citation_id": f"S{len(results) + 1}", "title": d["title"],
                            "source_uri": source, "citation_uri": f"{source}#L{c['start_line']}-L{c['end_line']}",
                            "revision": d["revision"], "document_sha256": d["sha256"],
                            "kind": d["kind"], "valid_from": d.get("valid_from"), "valid_until": d.get("valid_until"),
                            "score": round(scores[i], 6), "bm25_score": round(bm25.get(i, 0), 6),
                            "cosine_score": round(dense[i], 6) if i in dense else None,
                            "query_coverage": round(coverage[i], 4)})
            selected.append(c)
            if len(results) >= top_k:
                break
        return results
