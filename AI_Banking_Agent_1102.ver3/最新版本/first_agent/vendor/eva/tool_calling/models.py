"""Core datatypes for Module 6's tool-calling layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from ..models import new_id, utc_now
from .errors import ToolErrorDetail
from .utils import deep_copy_json, jsonable, new_evidence_id


IMPLEMENTATION_STATUSES = frozenset(
    {"implemented", "mocked", "awaiting_integration"}
)
RISK_TIERS = frozenset({"R0", "R1", "R2", "R3", "R4"})
RESULT_STATUSES = frozenset({"success", "error", "unknown"})


@dataclass(frozen=True)
class ToolCallContext:
    """Authenticated caller context; never accepted from model-generated args.

    `confirmed` / `confirmation_id` are the orchestration layer's admission
    control for state-changing tools. They are intentionally not part of a
    tool's JSON input schema, so an LLM cannot set them by producing arguments.
    Production authentication remains delegated to the existing approval system.
    """

    user_id: str
    session_id: str
    permissions: frozenset[str]
    request_text: str = ""
    auth_level: str = "strong"
    confirmed: bool = False
    confirmation_id: str | None = None
    step_up_verified: bool = False
    idempotency_key: str | None = None
    trace_id: str = field(default_factory=lambda: new_id("TRACE"))
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.permissions, (set, list, tuple)):
            object.__setattr__(self, "permissions", frozenset(self.permissions))

    def public_dict(self) -> dict[str, Any]:
        """Context fields safe to put in a trace (no request text / secret)."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "permissions": sorted(self.permissions),
            "auth_level": self.auth_level,
            "confirmed": self.confirmed,
            "confirmation_present": bool(self.confirmation_id),
            "step_up_verified": self.step_up_verified,
            "trace_id": self.trace_id,
        }


@dataclass
class ToolDefinition:
    """A registered tool contract plus its deterministic implementation."""

    name: str
    description: str
    category: str
    handler: Callable[[dict[str, Any], ToolCallContext], dict[str, Any]]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    version: str = "1.0.0"
    mutating: bool = False
    risk_tier: str = "R1"
    permissions: tuple[str, ...] = ()
    requires_confirmation: bool = False
    requires_safety_checks: bool = False
    implementation_status: str = "implemented"
    data_sources: tuple[str, ...] = ()
    simulated: bool = False
    max_attempts: int = 1
    tags: tuple[str, ...] = ()

    @property
    def read_only(self) -> bool:
        return not self.mutating

    @property
    def requires_idempotency(self) -> bool:
        # Every mutation must be replay-safe. The registry requires a stable key
        # in the trusted ToolCallContext rather than in model-provided args.
        return self.mutating

    def discovery_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "read_only": self.read_only,
            "mutating": self.mutating,
            "risk_tier": self.risk_tier,
            "permissions": list(self.permissions),
            "requires_confirmation": self.requires_confirmation,
            "requires_idempotency": self.requires_idempotency,
            "requires_safety_checks": self.requires_safety_checks,
            "implementation_status": self.implementation_status,
            "data_sources": list(self.data_sources),
            "simulated": self.simulated,
            "max_attempts": self.max_attempts,
            "tags": list(self.tags),
            "input_schema": deep_copy_json(self.input_schema),
            "output_schema": deep_copy_json(self.output_schema),
        }


@dataclass
class EvidenceItem:
    """A source-linked fact produced by one successful tool call."""

    tool: str
    tool_version: str
    call_id: str
    trace_id: str
    sources: tuple[str, ...]
    summary: str
    payload: dict[str, Any]
    payload_hash: str
    implementation_status: str
    simulated: bool
    caveats: tuple[str, ...] = ()
    evidence_id: str = field(default_factory=new_evidence_id)
    collected_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "call_id": self.call_id,
            "trace_id": self.trace_id,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "sources": list(self.sources),
            "summary": self.summary,
            "payload": deep_copy_json(self.payload),
            "payload_hash": self.payload_hash,
            "implementation_status": self.implementation_status,
            "simulated": self.simulated,
            "caveats": list(self.caveats),
            "collected_at": self.collected_at,
        }


@dataclass
class EvidenceBundle:
    items: list[EvidenceItem] = field(default_factory=list)

    def add(self, evidence: EvidenceItem) -> None:
        self.items.append(evidence)

    def extend(self, items: Iterable[EvidenceItem]) -> None:
        self.items.extend(items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.items),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class ToolCallResult:
    """Standardized result envelope returned by every registry call."""

    tool: str
    version: str
    call_id: str
    ok: bool
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    error: ToolErrorDetail | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    evidence: EvidenceItem | None = None

    @property
    def summary(self) -> str:
        value = self.data.get("summary")
        return value if isinstance(value, str) else ""

    @property
    def error_code(self) -> str | None:
        return self.error.code if self.error else None

    @property
    def duplicate(self) -> bool:
        return bool(self.meta.get("duplicate"))

    def to_dict(self, *, include_evidence: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "tool": self.tool,
            "version": self.version,
            "call_id": self.call_id,
            "data": deep_copy_json(self.data),
            "error": self.error.to_dict() if self.error else None,
            "meta": deep_copy_json(self.meta),
        }
        if include_evidence and self.evidence is not None:
            payload["evidence"] = self.evidence.to_dict()
        return payload


def make_call_id() -> str:
    return new_id("CALL")
