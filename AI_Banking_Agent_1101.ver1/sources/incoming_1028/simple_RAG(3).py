from collections import Counter, defaultdict
from pathlib import Path
import math
import re
from uuid import uuid4

# =========================
# 1. 安全策略：越权/敏感请求直接拒答
# =========================
SENSITIVE_PATTERNS = [
    "他人", "别人", "朋友的", "家人的", "同事的", "丈夫", "妻子", "父母",
    "账户余额", "身份证号", "银行卡", "手机号", "银行卡号", "身份证",
    "查看别人", "查看他人", "看别人", "看他人", "别人的账单", "他人的账单",
    "转账给", "直接转账", "直接扣款", "直接退款", "隐私", "交易明细",
    "查看我朋友", "看我朋友", "看好友", "看同事"
]


def is_sensitive_or_unsafe(question: str) -> bool:
    q = question.lower()
    normalized = q
    return any(p.lower() in normalized for p in SENSITIVE_PATTERNS)


# =========================
# 2. 读取知识库
# =========================
def load_knowledge(base_dir: str):
    """读取 data/knowledge 下的 .md 文档，返回 {文件名: 内容}。"""
    knowledge = {}
    path = Path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"知识库目录不存在: {base_dir}")

    for file in sorted(path.glob("*.md")):
        text = file.read_text(encoding="utf-8")
        knowledge[file.name] = text

    return knowledge


# =========================
# 3. 文本清洗与中文分词
# =========================
def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str):
    """将中文按双字词 + 单字词／英文词进行粗粒度分词，便于快捷 BM25 召回。"""
    text = normalize_text(text)
    tokens = []

    # 提取中文连续段落
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(chunk) >= 2:
            tokens.extend([chunk[i:i + 2] for i in range(len(chunk) - 1)])
        tokens.extend(list(chunk))

    # 提取英文/数字单词
    for word in re.findall(r"[a-z0-9]+", text):
        tokens.append(word)

    # 过滤空字符串与过短词，保留实词
    filtered = []
    for token in tokens:
        if len(token.strip()) == 0:
            continue
        if len(token) == 1 and not re.fullmatch(r"[a-z0-9]", token):
            continue
        filtered.append(token)

    return filtered


# =========================
# 4. 文档分块
# =========================
def split_markdown_into_chunks(text: str, max_chars: int = 500):
    """按标题和段落切块，保留语义边界。"""
    cleaned = re.sub(r"\r\n", "\n", text).strip()
    if not cleaned:
        return []

    blocks = re.split(r"\n\s*\n+", cleaned)
    chunks = []
    buffer = ""

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if len(buffer) + len(block) <= max_chars:
            buffer = f"{buffer}\n{block}".strip() if buffer else block
        else:
            if buffer:
                chunks.append(buffer)
            buffer = block

    if buffer:
        chunks.append(buffer)

    return [c for c in chunks if c.strip()]


# =========================
# 5. BM25 检索
# =========================
def semantic_overlap_score(question: str, text: str) -> float:
    """计算问题与文本的重叠词比例，作为 BM25 的补充语义信号。"""
    q_tokens = set(tokenize(question))
    t_tokens = set(tokenize(text))
    if not q_tokens or not t_tokens:
        return 0.0

    overlap = q_tokens & t_tokens
    if not overlap:
        return 0.0

    union = q_tokens | t_tokens
    return len(overlap) / len(union)


def compute_tfidf_vectors(chunks):
    """为所有 chunk 构造一个简化版 TF-IDF 向量空间，用作语义检索补充。"""
    if not chunks:
        return [], {}, []

    vocab = sorted({term for chunk in chunks for term in set(tokenize(chunk["text"]))})
    doc_freq = {term: 0 for term in vocab}
    for chunk in chunks:
        for term in set(tokenize(chunk["text"])):
            if term in doc_freq:
                doc_freq[term] += 1

    idf = {}
    total_docs = len(chunks)
    for term in vocab:
        df = doc_freq.get(term, 1)
        idf[term] = math.log((1 + total_docs) / (1 + df)) + 1.0

    vectors = []
    for chunk in chunks:
        tf = Counter(tokenize(chunk["text"]))
        doc_len = len(tf) if tf else 1
        vec = {}
        for term in vocab:
            count = tf.get(term, 0)
            if count:
                vec[term] = (count / doc_len) * idf[term]
        vectors.append(vec)

    return vocab, idf, vectors


def cosine_similarity(vec_a, vec_b):
    """计算两个词向量的余弦相似度。"""
    if not vec_a or not vec_b:
        return 0.0

    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in set(vec_a) | set(vec_b))
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def vector_score(question_tokens, chunks):
    """基于简化 TF-IDF 空间的向量语义检索。"""
    if not chunks:
        return []

    vocab, idf, vectors = compute_tfidf_vectors(chunks)
    if not vocab:
        return []

    q_tf = Counter(tokenize(" ".join(question_tokens)))
    q_len = len(q_tf) if q_tf else 1
    q_vec = {}
    for term in vocab:
        count = q_tf.get(term, 0)
        if count:
            q_vec[term] = (count / q_len) * idf[term]

    ranked = []
    for idx, chunk in enumerate(chunks):
        sim = cosine_similarity(q_vec, vectors[idx])
        if sim > 0:
            ranked.append({
                "source": chunk["source"],
                "title": chunk["title"],
                "text": chunk["text"],
                "score": round(sim, 4),
            })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def bm25_score(question_tokens, chunks, k1=1.5, b=0.75):
    """简单 BM25 公式，适合中文短文本检索，并加入语义重叠和向量相似度补偿。"""
    if not chunks:
        return []

    total_len = sum(len(tokenize(c["text"])) for c in chunks)
    avgdl = total_len / len(chunks)
    doc_freq = defaultdict(int)
    for chunk in chunks:
        doc_terms = set(tokenize(chunk["text"]))
        for term in doc_terms:
            doc_freq[term] += 1

    scored = []
    q_terms = [t for t in question_tokens if t]

    for idx, chunk in enumerate(chunks):
        terms = tokenize(chunk["text"])
        tf = Counter(terms)
        score = 0.0
        doc_len = len(terms)

        for term in q_terms:
            if term not in tf:
                continue
            df = doc_freq.get(term, 1)
            idf = math.log((len(chunks) - df + 0.5) / (df + 0.5) + 1.0)
            tf_val = tf[term]
            denom = tf_val + k1 * (1 - b + b * (doc_len / avgdl if avgdl > 0 else 1.0))
            score += idf * ((tf_val * (k1 + 1)) / denom)

        if q_terms:
            normalized_text = normalize_text(chunk["text"])
            for token in q_terms:
                if token in normalized_text:
                    score += 0.5

        semantic_bonus = semantic_overlap_score(" ".join(q_terms), chunk["text"]) * 6.0
        score += semantic_bonus

        if score > 0:
            scored.append({
                "source": chunk["source"],
                "title": chunk["title"],
                "text": chunk["text"],
                "score": round(score, 4),
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# =========================
# 6. 文档召回与答案生成
# =========================
def build_index(knowledge: dict):
    """将知识库内容转成可检索 chunk 索引。"""
    chunks = []
    for name, text in knowledge.items():
        title = name.replace(".md", "")
        for block in split_markdown_into_chunks(text):
            chunks.append({
                "source": name,
                "title": title,
                "text": block,
            })
    return chunks


def score_documents(question: str, knowledge: dict, top_k: int = 3):
    question_tokens = tokenize(question)
    if not question_tokens:
        return []

    chunks = build_index(knowledge)
    bm25_scored = bm25_score(question_tokens, chunks)
    vector_scored = vector_score(question_tokens, chunks)

    merged = {}
    for item in bm25_scored:
        merged[(item["source"], item["text"])] = item

    for item in vector_scored:
        key = (item["source"], item["text"])
        if key in merged:
            merged[key]["score"] = round(merged[key]["score"] + item["score"] * 5.0, 4)
        else:
            merged[key] = {
                **item,
                "score": round(item["score"] * 5.0, 4),
            }

    final = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    if not final:
        return []

    final = [item for item in final if item["score"] >= 2.0]
    if not final:
        return []

    return final[:top_k]


def retrieve(question: str, base_dir: str = "data/knowledge", top_k: int = 3):
    """对外查询接口：读取知识库、索引并返回 top-k 证据。"""
    knowledge = load_knowledge(base_dir)
    return score_documents(question, knowledge, top_k=top_k)


def extract_summary(text: str, question: str, max_len: int = 350):
    """截取最相关片段，尽量保留问题对应证据。"""
    q_tokens = tokenize(question)
    if not q_tokens:
        return text[:max_len]

    paragraphs = re.split(r"\n\s*\n+", text)
    best_para = ""
    best_score = -1

    for para in paragraphs:
        para_norm = normalize_text(para)
        score = 0
        for token in q_tokens:
            if token in para_norm:
                score += 1
        if score > best_score:
            best_score = score
            best_para = para

    summary = best_para if best_para else text
    summary = summary.strip().replace("\n", " ")
    return summary[:max_len]


def build_contract_response(question: str, top_k: int, answer: str, evidence: list, status: str, risk_notice: str, error: dict | None = None):
    """将内部 RAG 结果包装成外部 API 契约格式。"""
    source_list = []
    evidence_list = []

    for item in evidence:
        source = item.get("source")
        if source and source not in source_list:
            source_list.append(source)

        evidence_list.append({
            "source": source,
            "title": item.get("title"),
            "score": item.get("score", 0.0),
            "snippet": extract_summary(item.get("text", ""), question, max_len=360),
        })

    return {
        "schema_version": "1.0.0",
        "request_id": uuid4().hex,
        "status": "succeeded" if error is None else "failed",
        "data": {
            "status": status,
            "answer": answer,
            "evidence": evidence_list,
            "sources": source_list,
            "risk_notice": risk_notice,
        },
        "error": error,
        "trace": {
            "question": question,
            "top_k": top_k,
            "evidence_count": len(evidence_list),
            "retrieval_mode": "bm25 + tfidf fallback",
        },
        "simulated": True,
    }


def rag_answer(question: str, base_dir: str = "data/knowledge", top_k: int = 3):
    # 先处理安全策略
    if is_sensitive_or_unsafe(question):
        return build_contract_response(
            question=question,
            top_k=top_k,
            answer="我不能直接访问他人的账户、隐私信息或执行相关金融操作。若这是用户的敏感财务请求，请先完成身份验证和授权流程，并转人工处理。",
            evidence=[],
            status="refused",
            risk_notice="越权访问 / 隐私保护 / 执行前确认",
        )

    knowledge = load_knowledge(base_dir)
    evidence = score_documents(question, knowledge, top_k=top_k)

    if not evidence:
        return build_contract_response(
            question=question,
            top_k=top_k,
            answer="我在当前知识库中没有找到足够相关的证据，无法做出可靠判断。建议补充时间范围、收入支出结构、交易状态或风险信息，并转人工确认。",
            evidence=[],
            status="no_evidence",
            risk_notice="信息不足 / 需人工确认",
        )

    # 如果前几条证据都偏低，说明问题和知识库主题不匹配，直接拒答，避免误答
    if evidence[0]["score"] < 4.0:
        return build_contract_response(
            question=question,
            top_k=top_k,
            answer="我没有在知识库中找到足够直接相关的证据，因此不能在当前信息下给出可靠结论。请补充具体时间、支出结构、交易状态或是否存在权限范围内的业务场景。",
            evidence=[],
            status="no_evidence",
            risk_notice="证据不足 / 需人工确认",
        )

    answer_parts = [
        "结论：",
        "基于知识库中的金融规则和典型场景，以下是我根据可核查证据给出的判断。",
        "\n依据：",
    ]

    for item in evidence:
        snippet = extract_summary(item["text"], question, max_len=360)
        answer_parts.append(f"- {item['source']}（相关度 {item['score']}）：{snippet}")

    answer_parts.extend([
        "\n风险提示：",
        "如果问题涉及异常交易、资金压力、权限访问或未确认执行操作，应保持审慎态度，并优先建议人工复核。",
        "\n进一步确认：",
        "如果用户未提供收入、支出、债务、时间范围或权限信息，应先补充这些关键事实，再给出结论。",
    ])

    final_answer = "\n".join(answer_parts)

    return build_contract_response(
        question=question,
        top_k=top_k,
        answer=final_answer,
        evidence=evidence,
        status="grounded",
        risk_notice="基于证据检索 / 安全边界 / 需人工确认",
    )


# =========================
# 7. 演示入口
# =========================
if __name__ == "__main__":
    demo_questions = [
        "为什么我的储蓄率下降了？",
        "我有时会突然收到一些小额扣款，不知道是不是系统问题",
        "帮我看一下我朋友的账户余额",
        "我最近总觉得钱不够花，但我也没特别大额消费",
        "为什么转账会延迟？"
    ]

    for q in demo_questions:
        print("=" * 60)
        print("问题：", q)
        result = rag_answer(q)
        print("状态：", result["data"]["status"])
        print("回答：", result["data"]["answer"])
        print("来源：", result["data"]["sources"])
        print("风险提示：", result["data"]["risk_notice"])
        print("=" * 60)