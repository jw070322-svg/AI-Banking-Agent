from pathlib import Path
import re

# =========================
# 1. 安全策略：越权/敏感请求直接拒答
# =========================
SENSITIVE_PATTERNS = [
    "他人", "别人", "朋友的", "家人的", "账户余额", "身份证号",
    "银行卡", "手机号", "转账给", "直接转账", "直接扣款", "直接退款",
    "查看别人", "查看他人", "别人的账单", "看他人", "看别人", "隐私"
]

def is_sensitive_or_unsafe(question: str) -> bool:
    q = question.lower()
    return any(p.lower() in q for p in SENSITIVE_PATTERNS)


# =========================
# 2. 读取知识库
# =========================
def load_knowledge(base_dir: str):
    """
    读取 data/knowledge 下的 .md 文档
    返回 {文件名: 内容}
    """
    knowledge = {}
    path = Path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"知识库目录不存在: {base_dir}")

    for file in sorted(path.glob("*.md")):
        text = file.read_text(encoding="utf-8")
        knowledge[file.name] = text

    return knowledge


# =========================
# 3. 文本清洗
# =========================
def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# =========================
# 4. 关键词打分
# =========================
def score_documents(question: str, knowledge: dict):
    q_tokens = [t for t in normalize_text(question).split() if t.strip()]

    scored = []
    for name, text in knowledge.items():
        text_norm = normalize_text(text)
        score = 0

        # 关键词命中加权
        for token in q_tokens:
            weight = 1 + len(token) / 10
            score += text_norm.count(token) * weight

        # 增强关键词：如果文档里出现金融核心词，给更多权重
        core_keywords = ["现金流", "储蓄率", "流动性", "债务", "风险", "合规", "预算", "订阅", "旅行"]
        for keyword in core_keywords:
            if keyword in text:
                score += 2

        scored.append((name, score))

    # 过滤低分
    scored = [(name, score) for name, score in scored if score > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# =========================
# 5. 提取文本摘要
# =========================
def extract_summary(text: str, question: str, max_len: int = 350):
    """
    这里先做一个简单摘要：
    - 取前 max_len 字符
    - 但优先保留和问题最相关段落
    """
    q_tokens = normalize_text(question).split()
    paragraphs = re.split(r"\n\s*\n", text)

    best_para = ""
    best_score = -1

    for para in paragraphs:
        p_norm = normalize_text(para)
        score = 0
        for token in q_tokens:
            if token in p_norm:
                score += 1
        if score > best_score:
            best_score = score
            best_para = para

    if best_para:
        summary = best_para
    else:
        summary = text[:max_len]

    return summary[:max_len]


# =========================
# 6. RAG 核心逻辑
# =========================
def rag_answer(question: str, base_dir: str = "data/knowledge", top_k: int = 3):
    # 先处理安全策略
    if is_sensitive_or_unsafe(question):
        return {
            "answer": "我不能直接访问他人的账户、隐私信息或执行相关金融操作。若这是用户的敏感财务请求，请先完成身份验证和授权流程，并转人工处理。",
            "sources": [],
            "risk_notice": "越权访问 / 隐私保护 / 执行前确认"
        }

    knowledge = load_knowledge(base_dir)
    scored = score_documents(question, knowledge)

    if not scored:
        return {
            "answer": "我在当前知识库里没有找到足够相关的信息，无法做出可靠判断。建议补充时间、收入、支出、风险状态或转人工确认。",
            "sources": [],
            "risk_notice": "信息不足 / 需人工确认"
        }

    top_docs = scored[:top_k]

    evidence = []
    for name, score in top_docs:
        text = knowledge[name]
        snippet = extract_summary(text, question, max_len=350)
        evidence.append({
            "source": name,
            "score": round(score, 2),
            "snippet": snippet
        })

    # 生成答案模板
    answer_parts = []
    answer_parts.append("结论：")
    answer_parts.append("基于当前知识库中的金融规则和典型场景，我给出以下判断。")

    answer_parts.append("\n依据：")
    for item in evidence:
        answer_parts.append(f"- {item['source']}：{item['snippet']}")

    answer_parts.append("\n风险提示：")
    answer_parts.append("若问题涉及现金流异常、隐私访问、越权查询或未确认执行操作，应优先保持保守态度，并建议转人工复核。")

    answer_parts.append("\n进一步确认：")
    answer_parts.append("若用户未提供足够时间范围、收入支出结构或权限信息，建议先补充数据后再下结论。")

    final_answer = "\n".join(answer_parts)

    return {
        "answer": final_answer,
        "sources": [item["source"] for item in evidence],
        "risk_notice": "依据检索 / 安全边界 / 需人工确认"
    }


# =========================
# 7. 演示入口
# =========================
if __name__ == "__main__":
    demo_questions = [
        "为什么我的储蓄率下降了？",
        "我有时会突然收到一些小额扣款，不知道是不是系统问题",
        "帮我看一下我朋友的账户余额",
        "我最近总觉得钱不够花，但我也没特别大额消费"
    ]

    for q in demo_questions:
        print("=" * 60)
        print("问题：", q)
        result = rag_answer(q)
        print(result["answer"])
        print("来源：", result["sources"])
        print("风险提示：", result["risk_notice"])
        print("=" * 60)