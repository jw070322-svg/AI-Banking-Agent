"""词库加载与事件→搜索关键词提取（规则基线，非千问推理）。

词库外置于 data/lexicon.json 并带 lexicon_version，供计划与交接审计引用。
否定仅做"否定前缀+关键词"连续匹配的基线处理；复杂否定、多意图必须
转结构化模型评审（DESIGN §3），不得宣称完整理解。
"""
import json
from pathlib import Path

DEFAULT_LEXICON = Path(__file__).parent / "data" / "lexicon.json"

# 内置兜底：仅当词库文件缺失或损坏时使用，并在 keyword_source 中如实标注。
BUILTIN_RULES = {"生日": ["生日餐厅", "蛋糕"], "纪念日": ["约会餐厅", "鲜花"],
                 "婚礼": ["婚宴"], "聚餐": ["聚餐餐厅"], "亲子": ["亲子餐厅"]}
_DEFAULT_NEGATION = ["不要", "不用", "无需", "不订", "不用订", "别订", "不想要"]


class LexiconError(ValueError):
    """词库结构或内容不合规。"""


def load_lexicon(path=None):
    path = Path(path) if path is not None else DEFAULT_LEXICON
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LexiconError(f"词库读取失败：{exc}") from None
    if not isinstance(data, dict):
        raise LexiconError("词库顶层必须是对象")
    version = data.get("lexicon_version")
    if not isinstance(version, str) or not version:
        raise LexiconError("缺少有效的 lexicon_version")
    categories = data.get("categories")
    if not isinstance(categories, list) or not categories:
        raise LexiconError("categories 必须为非空列表")
    seen = set()
    for category in categories:
        if not isinstance(category, dict):
            raise LexiconError("品类条目必须是对象")
        trigger = category.get("trigger")
        if not isinstance(trigger, str) or not trigger:
            raise LexiconError("品类缺少有效 trigger")
        if trigger in seen:
            raise LexiconError("品类重复：" + trigger)
        seen.add(trigger)
        keywords = category.get("search_keywords")
        if (not isinstance(keywords, list) or not keywords
                or not all(isinstance(k, str) and k for k in keywords)):
            raise LexiconError("品类 " + trigger + " 的 search_keywords 无效")
        priority = category.get("priority", 0)
        if type(priority) is not int:
            raise LexiconError("品类 " + trigger + " 的 priority 必须为整数")
    prefixes = data.get("negation_prefixes", _DEFAULT_NEGATION)
    if (not isinstance(prefixes, list) or not prefixes
            or not all(isinstance(p, str) and len(p) >= 2 for p in prefixes)):
        raise LexiconError("negation_prefixes 必须为长度≥2的非空字符串列表")
    return {"lexicon_version": version, "categories": categories,
            "negation_prefixes": prefixes}


def extract_keywords(event, lexicon):
    """返回 (keywords, negated_keywords, review_flags)。

    - 触发词命中后逐个关键词判断：'否定前缀+关键词'连续出现则排除并记入 negated。
    - review_flags 只用固定短语，绝不携带事件原文，保证交接脱敏性质。
    - 排序按 priority 稳定降序；同级保持词库声明顺序（兼容历史 RULES 顺序）。
    """
    keywords, negated, flags = [], [], []
    prefixes = lexicon["negation_prefixes"]
    ordered = sorted(lexicon["categories"], key=lambda c: -c.get("priority", 0))
    for category in ordered:
        if category["trigger"] not in event:
            continue
        for keyword in category["search_keywords"]:
            if keyword in keywords or keyword in negated:
                continue
            if any(prefix + keyword in event for prefix in prefixes):
                negated.append(keyword)
            else:
                keywords.append(keyword)
    if negated:
        flags.append("检测到明确否定：已按否定前缀排除对应关键词；规则否定为基线，建议模型或客户复核")
    if not negated and any(prefix in event for prefix in prefixes):
        flags.append("检测到疑似否定表述但未形成可靠的'前缀+关键词'连续匹配，需模型或客户确认品类")
    return keywords, negated, flags
