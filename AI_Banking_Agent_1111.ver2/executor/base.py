"""执行器基座：步骤记录、状态核验、waiting_user 状态机、证据链（DESIGN §4/§7）。

纪律（全部代码化，不靠自觉）：
- 每步执行后必须读取页面状态；与预期不一致不得继续（verify_state）。
- 默认每步 30 秒超时；仅只读/幂等操作允许重试一次（READ_ONLY_ACTIONS + needs_retry）。
- status=ok 必须携带 evidence_ref 且文件真实存在、哈希一致（record_step 强制）——
  不可能伪造成功记录。
- run.jsonl 追加只写；每行先过 execution_log.schema.json 再落盘。
- 登录墙/验证码 → waiting_user；页头常态"请登录"入口不算（避免误判，见 FORCE_WALL_KEYWORDS）。
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from schema_check import SchemaValidationError, load_schema, validate

from workflow import now

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_WAITING_USER = "waiting_user"
STATUS_SKIPPED = "skipped"

# 工作包A §4.1：目标裁决与运行结局分离
GOAL_SATISFIED = "satisfied"
GOAL_PARTIAL = "partial"
GOAL_BLOCKED = "blocked"
GOAL_FAILED = "failed"

STEP_TIMEOUT_SECONDS = 30
MAX_RETRIES = 1
READ_ONLY_ACTIONS = {"open_site", "select_city", "search", "resolve_location"}

# 触发 waiting_user 的页面特征（强制墙，而非常态入口）
FORCE_WALL_KEYWORDS = ["验证码", "滑动验证", "请输入验证码", "安全验证",
                       "校验码", "身份核实", "验证中心", "spiderindefence"]
# 常态页头元素，不构成 waiting_user（1111.ver2 交接口径：首页含"请登录/注册"）
NORMAL_LOGIN_HINTS = ["请登录", "登录/注册"]


def new_session_dir(base):
    """唯一会话目录（时间戳-uuid，同 write_handoff 风格），含 evidence 子目录。"""
    base = Path(base)
    target = base / (datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
                     + "-" + uuid.uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    (target / "evidence").mkdir()
    return target


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def url_host(url):
    """取URL主机名（小写）；解析失败返回空串。"""
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def domain_matches(url, expected_host):
    """按主机名判定当前站点。2026-11-12 实测教训：子串包含会把重定向
    回调参数里的域名（如 succCallbackUrl=https%3A%2F%2Fwww.dianping.com）
    误判为已到达官网——必须用主机名判定。"""
    return url_host(url) == (expected_host or "").lower()


def detect_waiting_user(state_summary):
    """强制墙检测：命中 FORCE_WALL_KEYWORDS 即 waiting_user；
    常态"请登录"入口不算（返回 None）。"""
    text = state_summary or ""
    for keyword in FORCE_WALL_KEYWORDS:
        if keyword in text:
            return f"页面出现强制验证特征：{keyword}"
    return None


def verify_state(expected, observed):
    """逐键核对页面状态；不一致即中止依据。返回 (ok, message)。"""
    for key, want in (expected or {}).items():
        got = (observed or {}).get(key)
        if want is True:  # 布尔断言：observed[key] 为真即可（由采集方预先计算）
            if not got:
                return False, f"状态核验失败：{key} 预期成立，实际 {got!r}"
        elif got != want:
            return False, f"状态核验失败：{key} 预期 {want!r}，实际 {got!r}"
    return True, "一致"


def needs_retry(action, status, retries):
    """只读/幂等动作失败且未用尽次数时允许重试一次。"""
    return status == STATUS_FAILED and action in READ_ONLY_ACTIONS and retries < MAX_RETRIES


class ExecutionLog:
    """run.jsonl 追加只写日志；每行先过契约再落盘（DESIGN §7）。"""

    def __init__(self, session_dir):
        self.session_dir = Path(session_dir)
        self.path = self.session_dir / "run.jsonl"
        self.schema = load_schema("execution_log.schema.json")

    def _append(self, record):
        try:
            validate(record, self.schema)
        except SchemaValidationError as exc:
            raise ValueError(f"步骤记录不符合契约，拒绝落盘：{exc}") from None
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def run_start(self, customer_ref, mode="readonly_observation"):
        return self._append({"type": "run_start", "timestamp": now(),
                             "run_id": uuid.uuid4().hex[:12],
                             "customer_ref": customer_ref, "mode": mode})

    def load_lines(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in
                self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def record_step(self, *, seq, action, params, started_at, ended_at, duration_ms,
                    status, error_code=None, retries=0, response_summary=None,
                    evidence_ref=None, action_source=None, execution_method=None,
                    skip_reason=None, required_for_goal=None,
                    postcondition_evidence=None, plan_hash=None, step_id=None,
                    attempt=None, machine_verdict=None, machine_verdict_reason=None):
        if status == STATUS_OK and not evidence_ref:
            raise ValueError("status=ok 必须携带 evidence_ref；禁止无证据的成功记录")
        if status == STATUS_SKIPPED and not skip_reason:
            raise ValueError("skipped 步骤必须提供 skip_reason；不允许无因跳过（§4.1）")
        if evidence_ref:
            rel_path = evidence_ref.split("#")[0]
            claimed = None
            if "#sha256:" in evidence_ref:
                claimed = evidence_ref.split("#sha256:", 1)[1]
            file_path = self.session_dir / rel_path
            if not file_path.is_file():
                raise ValueError(f"证据文件不存在：{rel_path}；禁止伪造成功记录")
            if claimed:
                actual = sha256_of(file_path)
                if not actual.startswith(claimed):
                    raise ValueError(f"证据哈希不一致：声明 {claimed}，实际 {actual[:len(claimed)]}")
        for entry in (postcondition_evidence or []):
            pe_path = self.session_dir / entry["evidence_ref"].split("#")[0]
            if not pe_path.is_file():
                raise ValueError(f"后置条件证据文件不存在：{entry['evidence_ref']}")
            if not sha256_of(pe_path).startswith(entry["sha256"]):
                raise ValueError(f"后置条件证据哈希不一致：{entry['key']}")
        return self._append({"type": "step", "timestamp": now(), "seq": seq,
                             "action": action, "params": params or {},
                             "started_at": started_at, "ended_at": ended_at,
                             "duration_ms": duration_ms, "status": status,
                             "error_code": error_code, "retries": retries,
                             "response_summary": response_summary,
                             "evidence_ref": evidence_ref,
                             "action_source": action_source,
                             "execution_method": execution_method,
                             "skip_reason": skip_reason,
                             "required_for_goal": required_for_goal,
                             "postcondition_evidence": postcondition_evidence,
                             "plan_hash": plan_hash, "step_id": step_id,
                             "attempt": attempt,
                             "machine_verdict": machine_verdict,
                             "machine_verdict_reason": machine_verdict_reason})

    def record_session_end(self, *, run_outcome, goal_outcome, note=None,
                           finished_at=None, run_id=None, goal_outcome_annotation=None):
        """会话双结局（§4.1 + S1.2）：run_outcome=执行终止方式；goal_outcome=机器裁决；
        goal_outcome_annotation=人工评估注解（仅记录，永不覆盖机器裁决）。"""
        return self._append({"type": "session_end", "timestamp": now(),
                             "run_id": run_id, "run_outcome": run_outcome,
                             "goal_outcome": goal_outcome,
                             "goal_outcome_annotation": goal_outcome_annotation,
                             "note": note, "finished_at": finished_at or now()})


def evidence_ref_for(session_dir, file_path):
    """相对路径#sha256前缀，便于 record_step 校验。"""
    path = Path(file_path)
    rel = path.resolve().relative_to(Path(session_dir).resolve()).as_posix()
    return f"{rel}#sha256:{sha256_of(path)[:16]}"
