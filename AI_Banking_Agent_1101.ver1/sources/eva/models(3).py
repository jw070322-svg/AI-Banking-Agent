"""贯穿整条流水线的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# 工具 scope 白名单：注册表只接受这些权限，避免模块层“默认放行”。
ALLOWED_SCOPES = {
    "account:read",
    "transactions:read",
    "transfer:write",
    "card:read",
    "card:write",
    "loan:read",
    "audit:write",
}

# Demo 用户默认拥有全部业务 scope；真实环境由认证/授权服务下发。
DEMO_SCOPES = frozenset(ALLOWED_SCOPES)


class Status(str, Enum):
    COMPLETED = "completed"
    NEEDS_INPUT = "needs_input"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class IntentName(str, Enum):
    BALANCE = "balance_inquiry"
    TRANSACTIONS = "transaction_query"
    TRANSFER = "transfer"
    CARD_FREEZE = "card_freeze"
    LOAN = "loan_status"
    UNKNOWN = "unknown"


INTENT_LABELS = {
    IntentName.BALANCE.value: "余额查询",
    IntentName.TRANSACTIONS.value: "交易/消费查询",
    IntentName.TRANSFER.value: "转账",
    IntentName.CARD_FREEZE.value: "卡片冻结",
    IntentName.LOAN.value: "贷款查询",
    IntentName.UNKNOWN.value: "未识别意图",
}

STATUS_LABELS = {
    "completed": "已完成",
    "needs_input": "等待补充信息",
    "needs_confirmation": "等待用户确认",
    "cancelled": "已取消",
    "rejected": "已拦截",
    "failed": "执行异常",
    "unsupported": "暂不支持",
}

# 这些错误属于“业务上明确拒绝”，不是系统故障。只要发生在资金变动之前，
# 结果就是可安全交付的，无需人工复核。
CONTROLLED_REJECTION_CODES = {
    "POLICY_DENIED",
    "ACCOUNT_NOT_FOUND",
    "BENEFICIARY_NOT_FOUND",
    "CARD_NOT_FOUND",
    "UNSUPPORTED_ACCOUNT",
    "INVALID_ARGUMENT",
    # Risk & Compliance 的受控拒绝：预览/确认失效时停止，未发生资金变动
    "PREVIEW_EXPIRED",
    "PREVIEW_STALE",
    "APPROVAL_REQUIRED",
    "APPROVAL_INVALID",
    "POLICY_CHANGED",
    "TOOL_NOT_REGISTERED",
    "AUTH_INSUFFICIENT",
}


class ToolError(Exception):
    """工具层可预期的业务错误。"""

    def __init__(self, code: str, message: str, data: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


@dataclass
class Intent:
    name: str
    confidence: float
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW
    rationale: str = ""


@dataclass
class PlanStep:
    step_id: str
    title: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    mutating: bool = False
    requires_confirmation: bool = False


@dataclass
class Plan:
    plan_id: str
    intent: Intent
    steps: list[PlanStep]
    summary: str


@dataclass
class ToolSpec:
    name: str
    description: str
    required_args: tuple[str, ...]
    handler: Any  # Callable[..., dict[str, Any]]
    mutating: bool = False
    inject_idempotency_key: bool = False
    # Risk & Compliance 注册信息：风险等级只能由注册表声明，运行时不可降低。
    risk_tier: str = "R1"
    version: str = "1.0.0"
    requires_step_up: bool = False
    scopes: tuple[str, ...] = ()


@dataclass
class ToolResult:
    step_id: str
    tool: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    duplicate: bool = False
    elapsed_ms: float = 0.0


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerificationReport:
    passed: bool
    checks: list[Check] = field(default_factory=list)


@dataclass
class TraceEvent:
    stage: str
    ok: bool
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    at: str = field(default_factory=utc_now)


@dataclass
class PendingAction:
    plan: Plan
    results: list[ToolResult]
    next_step_index: int
    trace_prefix: list[TraceEvent] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    # risk.RiskAssessment；跨轮保存预览、策略检查与风险等级。
    risk_state: Any = None


@dataclass
class Session:
    session_id: str
    customer_id: str
    identity_level: str = "strong"  # strong = 已通过手机银行登录 + 设备绑定
    scopes: set[str] = field(default_factory=lambda: set(DEMO_SCOPES))
    pending: Optional[PendingAction] = None
    pending_clarification: Optional[Intent] = None
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentResponse:
    status: str
    text: str
    audit_id: str
    intent: Optional[Intent] = None
    plan: Optional[Plan] = None
    results: list[ToolResult] = field(default_factory=list)
    verification: Optional[VerificationReport] = None
    trace: list[TraceEvent] = field(default_factory=list)
    # risk.RiskAssessment：风险等级、策略检查、预览/审批信息
    risk: Any = None
