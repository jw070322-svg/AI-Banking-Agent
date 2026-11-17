"""本地千问客户端（DESIGN §3）。

边界与纪律：
- 只把 special_event 原文发送到本地模型服务（127.0.0.1:8797）；城市、预算、人数
  等字段绝不进入请求，因此模型无权改写它们。
- 模型输出是"候选提取"，不是最终关键词：不能当购买指令，需规则基线、
  客户或结构化评审确认（DESIGN §3）。
- 严格 JSON 解析 + 严格 Schema 校验（qwen_output.schema.json）；最多一次
  格式修复；仍无效回退 needs_input——不猜测、不修补内容。
- 证据片段逐条与本地原文核对，不匹配的片段单独列出，不冒充已验证。
- 本客户端不做训练、不加载适配器、不宣称模型能力提升；基线量化见
  evaluate_gold_set.py 与 reports/phase1/。
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

from lexicon import LexiconError, load_lexicon
from schema_check import SchemaValidationError, load_schema, validate

DEFAULT_BASE_URL = "http://127.0.0.1:8797"
DEFAULT_MODEL = "banking-qwen2.5-0.5b"
DEFAULT_KEY_FILE = Path("F:/AI_Banking/local-ai/local-model.key")
DEFAULT_TIMEOUT_SECONDS = 60
# 提取JSON只需数百token；上限用于阻止重复循环耗尽上下文（基线评测实测风险）。
MAX_GENERATION_TOKENS = 512
# 首轮输出超过该长度视为异常（重复循环），跳过修复，避免修复请求超限。
MAX_FIRST_CONTENT_CHARS = 4000

SYSTEM_PROMPT = (
    "你是信息提取器。只输出一个JSON对象，不要输出任何其他文字、解释或markdown代码块。"
    "JSON字段固定为：service_categories(字符串数组)、public_keywords(字符串数组)、"
    "constraints(字符串数组)、needs_clarification(布尔值)、evidence_spans(字符串数组)。"
    "service_categories和public_keywords只能是公共服务品类词（如生日餐厅、蛋糕、"
    "约会餐厅、鲜花、婚宴、聚餐餐厅、亲子餐厅），不得包含预算、电话、姓名或事件原文。"
    "客户表示不要某项时，对应关键词不得出现在public_keywords中。"
    "evidence_spans中的每个元素必须是输入原文的连续子串。"
    "事件描述不完整或无法理解时，needs_clarification置为true且数组为空。"
)
REPAIR_PROMPT = (
    "上面的输出不是合法JSON或不符合字段契约。请重新只输出一个纯JSON对象："
    "不要markdown代码块、不要解释，字段固定为service_categories、public_keywords、"
    "constraints、needs_clarification、evidence_spans。"
)


class QwenClientError(RuntimeError):
    """客户端配置或协议层错误（区别于模型输出不合格）。"""


def _read_key(key_file):
    path = Path(key_file)
    if not path.is_file():
        raise QwenClientError(f"缺少本地密钥文件：{path}")
    key = path.read_text(encoding="utf-8-sig").strip()
    if not key:
        raise QwenClientError("本地密钥文件为空")
    return key


class QwenClient:
    """对 127.0.0.1:8797 的受限聊天补全客户端（temperature=0）。"""

    def __init__(self, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL,
                 key=None, key_file=DEFAULT_KEY_FILE, timeout=DEFAULT_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._key = key if key is not None else None
        self._key_file = key_file
        self.timeout = timeout

    @property
    def _auth(self):
        if self._key is None:
            self._key = _read_key(self._key_file)
        return "Bearer " + self._key

    def _request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Authorization": self._auth})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise QwenClientError(f"HTTP {exc.code}：{exc.reason}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise QwenClientError(f"本地模型服务不可达或响应异常：{exc}") from None

    def probe(self):
        """核验服务与 model id（DESIGN §3：接入前必须核验）。"""
        try:
            data = self._request("GET", "/v1/models")
        except QwenClientError as exc:
            return {"ok": False, "reason": str(exc), "model": self.model}
        ids = [m.get("id") or m.get("model") for m in data.get("data", [])]
        return {"ok": self.model in ids, "models": ids, "model": self.model,
                "reason": None if self.model in ids else f"模型 {self.model} 不在服务列表 {ids}"}

    def _complete(self, messages):
        payload = {"model": self.model, "temperature": 0,
                   "max_tokens": MAX_GENERATION_TOKENS, "messages": messages}
        data = self._request("POST", "/v1/chat/completions", payload)
        try:
            choice = data["choices"][0]
            return {"content": choice["message"]["content"],
                    "finish_reason": choice.get("finish_reason"),
                    "usage": data.get("usage")}
        except (KeyError, IndexError, TypeError) as exc:
            raise QwenClientError(f"响应缺少 choices[0].message.content：{exc}") from None

    @staticmethod
    def _strict_parse(content, schema):
        """严格解析：不剥围栏、不修补文本；失败返回原因字符串。"""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            return None, f"JSON解析失败：{exc}"
        try:
            validate(parsed, schema)
        except SchemaValidationError as exc:
            return None, f"Schema校验失败：{exc}"
        return parsed, None

    @staticmethod
    def _out_of_vocabulary(parsed):
        """词表越界标记（只标记不丢弃）：public_keywords/service_categories 中
        不在本地词库搜索词内的条目。模型把事件原文回显进关键词时会被此检查捕获，
        防止外发到点评。词库不可用时返回 None 表示未核验。"""
        try:
            lexicon = load_lexicon()
        except LexiconError:
            return None
        vocab = {k for c in lexicon["categories"] for k in c["search_keywords"]}
        listed = list(parsed.get("public_keywords", [])) + list(parsed.get("service_categories", []))
        return [k for k in listed if k not in vocab]

    def extract(self, event_text):
        """事件原文 → 受限候选提取结果（状态机：ok / needs_input / unavailable）。"""
        if not isinstance(event_text, str) or not event_text.strip():
            return {"status": "needs_input", "reason": "事件描述为空", "parsed": None,
                    "evidence": {"valid": [], "invalid": []}, "raw_content": None,
                    "repair_used": False, "raw_parse_ok": False, "finish_reason": None,
                    "out_of_vocabulary": None}
        schema = load_schema("qwen_output.schema.json")
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "客户特殊事件描述：" + event_text}]
        try:
            first = self._complete(messages)
        except QwenClientError as exc:
            return {"status": "unavailable", "reason": str(exc), "parsed": None,
                    "evidence": {"valid": [], "invalid": []}, "raw_content": None,
                    "repair_used": False, "raw_parse_ok": False, "finish_reason": None,
                    "out_of_vocabulary": None}
        parsed, error = self._strict_parse(first["content"], schema)
        result = {"status": None, "reason": None, "parsed": parsed,
                  "evidence": {"valid": [], "invalid": []},
                  "raw_content": first["content"],
                  "repair_used": False, "raw_parse_ok": parsed is not None,
                  "finish_reason": first["finish_reason"], "out_of_vocabulary": None}
        if parsed is None:
            if len(first["content"] or "") > MAX_FIRST_CONTENT_CHARS:
                return {**result, "status": "needs_input",
                        "reason": f"首轮输出异常过长（{len(first['content'])}字符，疑似重复循环），"
                                  "跳过修复以避免上下文超限"}
            # 最多一次格式修复（DESIGN §3），仍无效回退 needs_input
            repair_messages = messages + [{"role": "assistant", "content": first["content"]},
                                          {"role": "user", "content": REPAIR_PROMPT}]
            try:
                second = self._complete(repair_messages)
            except QwenClientError as exc:
                return {**result, "status": "unavailable", "reason": f"修复请求失败：{exc}"}
            result.update({"repair_used": True, "raw_content": second["content"],
                           "finish_reason": second["finish_reason"],
                           "raw_parse_ok": False})
            parsed, error = self._strict_parse(second["content"], schema)
            result["parsed"] = parsed
        if parsed is None:
            return {**result, "status": "needs_input",
                    "reason": f"一次格式修复后仍无效：{error}"}
        spans = parsed.get("evidence_spans", [])
        valid = [s for s in spans if isinstance(s, str) and s and s in event_text]
        invalid = [s for s in spans if s not in valid]
        return {**result, "status": "ok", "reason": None,
                "evidence": {"valid": valid, "invalid": invalid},
                "out_of_vocabulary": self._out_of_vocabulary(parsed)}
