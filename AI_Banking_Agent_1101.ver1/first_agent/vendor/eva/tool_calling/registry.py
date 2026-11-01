"""Centralized, validated, traced Tool Registry for Module 6.

The registry is intentionally separate from planning/orchestration. It knows how
to discover, authorize, validate and invoke a registered tool; it does not know
how to turn a user goal into a plan.
"""

from __future__ import annotations

import copy
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from ..models import ToolError as LegacyToolError
from .adapters import (
    ComplianceEvaluationRequest,
    ComplianceEvaluationResult,
    ComplianceGuardAdapter,
    RiskEngineAdapter,
    RiskEvaluationRequest,
    RiskEvaluationResult,
    UnconfiguredComplianceGuardAdapter,
    UnconfiguredRiskEngineAdapter,
    new_safety_request_id,
)
from .errors import (
    AUTH_INSUFFICIENT,
    COMPLIANCE_DENIED,
    COMPLIANCE_GUARD_ERROR,
    CONFIRMATION_INVALID,
    CONFIRMATION_REQUIRED,
    CONTROLLED_CODES,
    IDEMPOTENCY_CONFLICT,
    IDEMPOTENCY_KEY_REQUIRED,
    INTERNAL_ERROR,
    INVALID_ARGUMENTS,
    MUTATION_OUTCOME_UNKNOWN,
    PERMISSION_DENIED,
    RISK_DENIED,
    RISK_ENGINE_ERROR,
    SAFETY_CHECKS_UNAVAILABLE,
    TOOL_NOT_FOUND,
    TOOL_OUTPUT_INVALID,
    TOOL_UNAVAILABLE,
    ToolErrorDetail,
    ToolLayerError,
    ToolNotFoundError,
)
from .models import (
    IMPLEMENTATION_STATUSES,
    RISK_TIERS,
    EvidenceItem,
    ToolCallContext,
    ToolCallResult,
    ToolDefinition,
    make_call_id,
)
from .schema import apply_defaults, issues_to_dicts, validate_instance
from .services import ToolServices
from .tracing import InMemoryTraceSink, TraceSink, safe_emit
from .utils import deep_copy_json, now_iso, payload_hash


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass
class _IdempotencyRecord:
    fingerprint: str
    data: dict[str, Any]
    meta: dict[str, Any]
    evidence: EvidenceItem | None


class ToolRegistry:
    """Single registry, discovery surface, and dispatch path for Module 6."""

    def __init__(
        self,
        services: ToolServices | None = None,
        *,
        risk_engine: RiskEngineAdapter | None = None,
        compliance_guard: ComplianceGuardAdapter | None = None,
        allow_mock_safety: bool = False,
        trace_sink: TraceSink | None = None,
        auto_register: bool = True,
    ) -> None:
        self.services = services or ToolServices.demo()
        self.risk_engine = risk_engine or UnconfiguredRiskEngineAdapter()
        self.compliance_guard = (
            compliance_guard or UnconfiguredComplianceGuardAdapter()
        )
        # Mock safety adapters are never operational unless a test/demo opts in
        # explicitly. This flag does not make them "verified" production controls.
        self.allow_mock_safety = bool(allow_mock_safety)
        self._definitions: dict[str, ToolDefinition] = {}
        self._idempotency: dict[str, _IdempotencyRecord] = {}
        self._idempotency_lock = threading.RLock()
        self.trace_sink: TraceSink = trace_sink or InMemoryTraceSink()
        if auto_register:
            from .tools import register_core_tools

            register_core_tools(self, self.services)

    # ------------------------------------------------------------------
    # Registration and discovery
    # ------------------------------------------------------------------

    def register(self, definition: ToolDefinition) -> None:
        if not isinstance(definition, ToolDefinition):
            raise TypeError("definition must be a ToolDefinition")
        if not _NAME_RE.fullmatch(definition.name):
            raise ValueError(
                "tool name must match snake_case: ^[a-z][a-z0-9_]*$"
            )
        if not _VERSION_RE.fullmatch(definition.version):
            raise ValueError("tool version must be semantic x.y.z")
        if definition.name in self._definitions:
            raise ValueError(f"duplicate tool registration: {definition.name}")
        if not callable(definition.handler):
            raise ValueError("tool handler must be callable")
        if not definition.description.strip():
            raise ValueError("tool description must not be empty")
        if not definition.category.strip():
            raise ValueError("tool category must not be empty")
        if not isinstance(definition.input_schema, dict) or (
            definition.input_schema.get("type") != "object"
        ):
            raise ValueError("input_schema must be a JSON object schema")
        if definition.input_schema.get("additionalProperties") is not False:
            raise ValueError(
                "input_schema must set additionalProperties=false"
            )
        if not isinstance(definition.output_schema, dict) or (
            definition.output_schema.get("type") != "object"
        ):
            raise ValueError("output_schema must be a JSON object schema")
        if definition.output_schema.get("additionalProperties") is not False:
            raise ValueError(
                "output_schema must set additionalProperties=false"
            )
        if definition.risk_tier not in RISK_TIERS:
            raise ValueError(f"invalid risk tier: {definition.risk_tier}")
        if not definition.permissions:
            raise ValueError("every tool must declare at least one permission")
        if any(not item.strip() for item in definition.permissions):
            raise ValueError("permissions must be non-empty strings")
        if not definition.data_sources:
            raise ValueError("every tool must declare its data sources")
        if definition.implementation_status not in IMPLEMENTATION_STATUSES:
            raise ValueError(
                f"invalid implementation status: {definition.implementation_status}"
            )
        if definition.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if definition.mutating and definition.risk_tier not in {"R3", "R4"}:
            raise ValueError("mutating tools must be R3 or R4")
        if not definition.mutating and definition.requires_confirmation:
            raise ValueError("only mutating tools may require confirmation")
        if definition.mutating and not definition.requires_confirmation:
            raise ValueError("every mutating tool must require confirmation")
        if definition.risk_tier == "R4" and not definition.requires_safety_checks:
            raise ValueError("R4 tools must require safety checks")
        if definition.requires_safety_checks and not definition.mutating:
            raise ValueError("safety checks are reserved for state-changing tools")
        if definition.mutating:
            definition.max_attempts = 1
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ToolNotFoundError(name) from exc

    def get_definition(self, name: str) -> ToolDefinition:
        return self.get(name)

    get_tool = get_definition

    def names(self) -> list[str]:
        return list(self._definitions)

    def __contains__(self, name: object) -> bool:
        return name in self._definitions

    def __len__(self) -> int:
        return len(self._definitions)

    def categories(self) -> list[str]:
        return sorted({item.category for item in self._definitions.values()})

    def definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def discover(
        self,
        *,
        category: str | None = None,
        read_only: bool | None = None,
        implementation_status: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return LLM/tool-builder-safe discovery descriptors."""
        result = []
        for definition in self._definitions.values():
            if category and definition.category != category:
                continue
            if read_only is not None and definition.read_only != read_only:
                continue
            if (
                implementation_status
                and definition.implementation_status != implementation_status
            ):
                continue
            if tag and tag not in definition.tags:
                continue
            result.append(definition.discovery_dict())
        return result

    def describe(self, name: str) -> dict[str, Any]:
        return self.get(name).discovery_dict()

    describe_tool = describe

    def list_tools(self, **filters: Any) -> list[dict[str, Any]]:
        """Alias for discover(); kept explicit for agent/tool integrators."""
        return self.discover(**filters)

    def safety_status(self) -> dict[str, Any]:
        return {
            "risk_engine": self._adapter_state(self.risk_engine),
            "compliance_guard": self._adapter_state(self.compliance_guard),
            "allow_mock_safety": self.allow_mock_safety,
            "production_checks_active": False,
        }

    def trace_events(self) -> list[dict[str, Any]]:
        events = getattr(self.trace_sink, "events", None)
        if callable(events):
            return events()
        return []

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        context: ToolCallContext | None = None,
    ) -> ToolCallResult:
        """Invoke a registered tool and always return a standard result envelope.

        Expected validation/policy failures are results, not exceptions. A
        programming error (e.g. missing context) raises TypeError because no
        authenticated identity can be inferred safely.
        """
        if not isinstance(context, ToolCallContext):
            raise TypeError("an authenticated ToolCallContext is required")
        if not context.user_id or not context.session_id:
            raise TypeError("ToolCallContext requires user_id and session_id")

        call_id = make_call_id()
        started_at = now_iso()
        started_perf = time.perf_counter()
        raw_arguments = {} if arguments is None else arguments
        definition: ToolDefinition | None = None
        normalized: dict[str, Any] = {}
        safety_meta = self._default_safety_meta()
        meta = self._base_meta(
            call_id=call_id,
            trace_id=context.trace_id,
            started_at=started_at,
        )
        meta["tool"] = name
        meta["safety"] = safety_meta
        phase = "lookup"
        attempts_box = {"value": 0}
        request_hash = self._safe_hash(
            {"tool": name, "arguments": raw_arguments}
        )
        if request_hash:
            meta["request_hash"] = request_hash

        try:
            definition = self._definitions.get(name)
            if definition is None:
                raise ToolNotFoundError(name)
            meta.update(self._definition_meta(definition))
            safety_meta = self._initial_safety_for(definition)
            meta["safety"] = safety_meta
            safe_emit(
                self.trace_sink,
                {
                    "event": "tool_call_started",
                    "trace_id": context.trace_id,
                    "call_id": call_id,
                    "tool": definition.name,
                    "version": definition.version,
                    "input_hash": request_hash,
                },
            )

            phase = "input_validation"
            normalized = self._normalize_arguments(definition, raw_arguments)
            meta["request_hash"] = payload_hash(
                {
                    "tool": definition.name,
                    "version": definition.version,
                    "user_id": context.user_id,
                    "arguments": normalized,
                }
            )

            phase = "authorization"
            self._check_permissions(definition, context)
            self._check_confirmation(definition, context)

            phase = "idempotency"
            idempotency_key: str | None = None
            fingerprint: str | None = None
            if definition.mutating:
                idempotency_key = (context.idempotency_key or "").strip()
                if not idempotency_key:
                    raise ToolLayerError(
                        IDEMPOTENCY_KEY_REQUIRED,
                        "该工具会改变状态，必须提供稳定的幂等键。",
                    )
                fingerprint = payload_hash(
                    {
                        "tool": definition.name,
                        "version": definition.version,
                        "user_id": context.user_id,
                        "arguments": normalized,
                    }
                )
                meta["idempotency_key_hash"] = payload_hash(
                    {"key": idempotency_key}
                )
                replay = self._lookup_idempotent(
                    idempotency_key, fingerprint
                )
                if replay is not None:
                    return self._build_replay_result(
                        definition,
                        replay,
                        normalized=normalized,
                        call_id=call_id,
                        context=context,
                        started_at=started_at,
                        started_perf=started_perf,
                    )

            phase = "safety"
            safety_meta = self._run_safety(
                definition, normalized, context, safety_meta
            )
            meta["safety"] = safety_meta

            phase = "handler"
            data = self._invoke_handler(
                definition,
                normalized,
                context,
                attempts_box=attempts_box,
            )
            meta["attempts"] = attempts_box["value"]

            phase = "output_validation"
            if not isinstance(data, dict):
                raise ToolLayerError(
                    TOOL_OUTPUT_INVALID,
                    "工具返回值不是对象，已按契约失败处理。",
                )
            issues = validate_instance(data, definition.output_schema)
            if issues:
                raise ToolLayerError(
                    TOOL_OUTPUT_INVALID,
                    "工具输出未通过输出契约校验。",
                    details={"issues": issues_to_dicts(issues)},
                )

            data = copy.deepcopy(data)
            finished_at = now_iso()
            evidence = self._build_evidence(
                definition, data, call_id, context.trace_id
            )
            meta.update(
                {
                    "finished_at": finished_at,
                    "duration_ms": round(
                        (time.perf_counter() - started_perf) * 1000, 3
                    ),
                    "evidence_id": evidence.evidence_id,
                    "duplicate": False,
                    "phase": "completed",
                }
            )
            result = ToolCallResult(
                tool=definition.name,
                version=definition.version,
                call_id=call_id,
                ok=True,
                status="success",
                data=data,
                meta=meta,
                evidence=evidence,
            )
            if definition.mutating and idempotency_key and fingerprint:
                self._store_idempotent(
                    idempotency_key, fingerprint, result
                )
            safe_emit(
                self.trace_sink,
                {
                    "event": "tool_call_completed",
                    "trace_id": context.trace_id,
                    "call_id": call_id,
                    "tool": definition.name,
                    "version": definition.version,
                    "status": "success",
                    "duration_ms": meta["duration_ms"],
                    "output_hash": evidence.payload_hash,
                    "safety": self._trace_safety(safety_meta),
                },
            )
            return result

        except ToolLayerError as exc:
            return self._error_result(
                definition=definition,
                call_id=call_id,
                context=context,
                started_at=started_at,
                started_perf=started_perf,
                meta=meta,
                safety_meta=safety_meta,
                error=exc.to_detail(),
                phase=phase,
                attempts=attempts_box["value"],
            )
        except LegacyToolError as exc:
            error = ToolErrorDetail(
                code=exc.code,
                message=exc.message,
                retryable=False,
                details=dict(exc.data or {}),
            )
            return self._error_result(
                definition=definition,
                call_id=call_id,
                context=context,
                started_at=started_at,
                started_perf=started_perf,
                meta=meta,
                safety_meta=safety_meta,
                error=error,
                phase=phase,
                attempts=attempts_box["value"],
            )
        except NotImplementedError:
            return self._error_result(
                definition=definition,
                call_id=call_id,
                context=context,
                started_at=started_at,
                started_perf=started_perf,
                meta=meta,
                safety_meta=safety_meta,
                error=ToolErrorDetail(
                    code=TOOL_UNAVAILABLE,
                    message="工具实现尚未接通，已拒绝执行。",
                ),
                phase=phase,
                attempts=attempts_box["value"],
            )
        except Exception as exc:
            mutating_handler_failure = bool(
                definition and definition.mutating and phase in {"handler"}
            )
            code = (
                MUTATION_OUTCOME_UNKNOWN
                if mutating_handler_failure
                else INTERNAL_ERROR
            )
            message = (
                "工具执行时发生未预期错误，结果为未知；禁止自动重试，需人工核对。"
                if mutating_handler_failure
                else "工具执行时发生未预期错误，未返回不可信结果。"
            )
            return self._error_result(
                definition=definition,
                call_id=call_id,
                context=context,
                started_at=started_at,
                started_perf=started_perf,
                meta=meta,
                safety_meta=safety_meta,
                error=ToolErrorDetail(
                    code=code,
                    message=message,
                    retryable=False,
                    details={"exception_type": type(exc).__name__},
                ),
                phase=phase,
                attempts=attempts_box["value"],
                force_unknown=mutating_handler_failure,
            )

    invoke = execute
    call = execute

    # ------------------------------------------------------------------
    # Input / authorization / idempotency helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_arguments(
        definition: ToolDefinition, arguments: Any
    ) -> dict[str, Any]:
        if not isinstance(arguments, Mapping):
            raise ToolLayerError(
                INVALID_ARGUMENTS,
                "tool arguments must be an object.",
            )
        normalized = apply_defaults(dict(arguments), definition.input_schema)
        issues = validate_instance(normalized, definition.input_schema)
        if issues:
            raise ToolLayerError(
                INVALID_ARGUMENTS,
                "工具参数未通过输入契约校验。",
                details={"issues": issues_to_dicts(issues)},
            )
        return normalized

    @staticmethod
    def _check_permissions(
        definition: ToolDefinition, context: ToolCallContext
    ) -> None:
        missing = sorted(set(definition.permissions) - set(context.permissions))
        if missing:
            raise ToolLayerError(
                PERMISSION_DENIED,
                "当前会话缺少调用该工具所需权限。",
                details={
                    "tool": definition.name,
                    "missing_permissions": missing,
                },
            )

    @staticmethod
    def _check_confirmation(
        definition: ToolDefinition, context: ToolCallContext
    ) -> None:
        if not definition.requires_confirmation:
            return
        if not context.confirmed:
            raise ToolLayerError(
                CONFIRMATION_REQUIRED,
                "该工具会改变状态，必须先获得明确的用户确认。",
                details={"tool": definition.name},
            )
        if not context.confirmation_id:
            raise ToolLayerError(
                CONFIRMATION_INVALID,
                "确认标记存在但缺少确认 ID，已拒绝执行。",
                details={"tool": definition.name},
            )

    def _lookup_idempotent(
        self, key: str, fingerprint: str
    ) -> _IdempotencyRecord | None:
        with self._idempotency_lock:
            record = self._idempotency.get(key)
            if record is None:
                return None
            if record.fingerprint != fingerprint:
                raise ToolLayerError(
                    IDEMPOTENCY_CONFLICT,
                    "同一幂等键已用于不同请求，已拒绝执行。",
                    details={
                        "idempotency_key_hash": payload_hash({"key": key})
                    },
                )
            return copy.deepcopy(record)

    def _store_idempotent(
        self,
        key: str,
        fingerprint: str,
        result: ToolCallResult,
    ) -> None:
        record = _IdempotencyRecord(
            fingerprint=fingerprint,
            data=copy.deepcopy(result.data),
            meta=copy.deepcopy(result.meta),
            evidence=copy.deepcopy(result.evidence),
        )
        with self._idempotency_lock:
            existing = self._idempotency.get(key)
            if existing is None:
                self._idempotency[key] = record
            elif existing.fingerprint != fingerprint:
                # This can only be reached through a concurrent race, after the
                # handler has already run. Never overwrite the first record.
                return

    def _build_replay_result(
        self,
        definition: ToolDefinition,
        record: _IdempotencyRecord,
        *,
        normalized: dict[str, Any],
        call_id: str,
        context: ToolCallContext,
        started_at: str,
        started_perf: float,
    ) -> ToolCallResult:
        meta = copy.deepcopy(record.meta)
        finished_at = now_iso()
        meta.update(
            {
                "trace_id": context.trace_id,
                "call_id": call_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": round(
                    (time.perf_counter() - started_perf) * 1000, 3
                ),
                "duplicate": True,
                "original_call_id": record.meta.get("call_id"),
                "phase": "idempotent_replay",
                "attempts": 0,
                "safety_reused_from_original": True,
            }
        )
        meta["request_hash"] = payload_hash(
            {
                "tool": definition.name,
                "version": definition.version,
                "user_id": context.user_id,
                "arguments": normalized,
            }
        )
        safe_emit(
            self.trace_sink,
            {
                "event": "tool_call_replayed",
                "trace_id": context.trace_id,
                "call_id": call_id,
                "tool": definition.name,
                "version": definition.version,
                "status": "success",
                "duration_ms": meta["duration_ms"],
                "original_call_id": record.meta.get("call_id"),
            },
        )
        return ToolCallResult(
            tool=definition.name,
            version=definition.version,
            call_id=call_id,
            ok=True,
            status="success",
            data=copy.deepcopy(record.data),
            meta=meta,
            evidence=copy.deepcopy(record.evidence),
        )

    # ------------------------------------------------------------------
    # Safety adapters
    # ------------------------------------------------------------------

    @staticmethod
    def _default_safety_meta() -> dict[str, Any]:
        return {
            "required": False,
            "production_checks_active": False,
            "compliance": {
                "status": "not_run",
                "adapter_kind": "unconfigured",
                "is_connected": False,
                "verified": False,
            },
            "risk": {
                "status": "not_run",
                "adapter_kind": "unconfigured",
                "is_connected": False,
                "verified": False,
            },
        }

    def _adapter_state(self, adapter: Any) -> dict[str, Any]:
        adapter = adapter or UnconfiguredRiskEngineAdapter()
        kind = str(getattr(adapter, "adapter_kind", "unconfigured"))
        connected = bool(getattr(adapter, "is_connected", False))
        verified = bool(getattr(adapter, "is_verified", False))
        name = str(getattr(adapter, "adapter_name", adapter.__class__.__name__))
        ready = False
        if not connected or kind == "unconfigured":
            status = "not_connected"
        elif kind == "mock":
            ready = self.allow_mock_safety
            status = "ready_mock" if ready else "disabled_mock"
        elif kind == "production":
            ready = verified
            status = "ready" if ready else "not_verified"
        else:
            status = "unsupported_adapter_kind"
        return {
            "adapter": name,
            "adapter_kind": kind,
            "is_connected": connected,
            "verified": verified,
            "ready": ready,
            "status": status,
        }

    def _initial_safety_for(
        self, definition: ToolDefinition
    ) -> dict[str, Any]:
        compliance_state = self._adapter_state(self.compliance_guard)
        risk_state = self._adapter_state(self.risk_engine)
        return {
            "required": definition.requires_safety_checks,
            "production_checks_active": False,
            "compliance": {**compliance_state},
            "risk": {
                **risk_state,
                "status": (
                    risk_state["status"]
                    if definition.mutating
                    else "not_required"
                ),
            },
        }

    def _run_safety(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolCallContext,
        safety: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        compliance_state = self._adapter_state(self.compliance_guard)
        risk_state = self._adapter_state(self.risk_engine)
        safety = safety if safety is not None else self._initial_safety_for(
            definition
        )
        safety.update(
            {
                "required": definition.requires_safety_checks,
                "production_checks_active": False,
                "compliance": {
                    **compliance_state,
                    "status": compliance_state["status"],
                },
                "risk": {
                    **risk_state,
                    "status": (
                        risk_state["status"]
                        if definition.mutating
                        else "not_required"
                    ),
                },
            }
        )

        if definition.requires_safety_checks:
            missing = []
            if not compliance_state["ready"]:
                missing.append("compliance_guard")
            if not risk_state["ready"]:
                missing.append("risk_engine")
            if missing:
                safety["compliance"]["status"] = compliance_state["status"]
                safety["risk"]["status"] = risk_state["status"]
                raise ToolLayerError(
                    SAFETY_CHECKS_UNAVAILABLE,
                    (
                        "该操作要求已接通并验证的 Risk Engine 与 Compliance Guard；"
                        "当前适配器未就绪，已失败关闭。"
                    ),
                    details={
                        "missing_checks": missing,
                        "risk_engine": risk_state,
                        "compliance_guard": compliance_state,
                    },
                )

        if compliance_state["ready"]:
            request = ComplianceEvaluationRequest(
                request_id=new_safety_request_id(),
                trace_id=context.trace_id,
                user_id=context.user_id,
                session_id=context.session_id,
                tool_name=definition.name,
                tool_version=definition.version,
                request_text=context.request_text,
                arguments=copy.deepcopy(arguments),
            )
            try:
                compliance_result = self.compliance_guard.evaluate(request)
            except Exception as exc:
                safety["compliance"].update(
                    {"status": "error", "error_type": type(exc).__name__}
                )
                raise ToolLayerError(
                    COMPLIANCE_GUARD_ERROR,
                    "Compliance Guard 适配器异常，已失败关闭。",
                ) from exc
            if not isinstance(compliance_result, ComplianceEvaluationResult):
                safety["compliance"]["status"] = "invalid_result"
                raise ToolLayerError(
                    COMPLIANCE_GUARD_ERROR,
                    "Compliance Guard 返回了不符合契约的结果，已失败关闭。",
                )
            is_mock = compliance_state["adapter_kind"] == "mock"
            safety["compliance"].update(
                {
                    "status": "evaluated_mock" if is_mock else "evaluated",
                    "decision_id": compliance_result.decision_id,
                    "policy_version": compliance_result.policy_version,
                    "finding_codes": [
                        str(item.get("code", "UNKNOWN"))
                        for item in compliance_result.findings
                        if isinstance(item, Mapping)
                    ],
                    "reasons": list(compliance_result.reasons),
                }
            )
            if not compliance_result.allowed:
                raise ToolLayerError(
                    COMPLIANCE_DENIED,
                    "Compliance Guard 拒绝了该工具调用。",
                    details={
                        "decision_id": compliance_result.decision_id,
                        "reasons": list(compliance_result.reasons),
                    },
                )

        if definition.mutating and risk_state["ready"]:
            request = RiskEvaluationRequest(
                request_id=new_safety_request_id(),
                trace_id=context.trace_id,
                user_id=context.user_id,
                session_id=context.session_id,
                tool_name=definition.name,
                tool_version=definition.version,
                mutating=definition.mutating,
                risk_tier=definition.risk_tier,
                permissions=definition.permissions,
                arguments=copy.deepcopy(arguments),
                request_text=context.request_text,
                auth_level=context.auth_level,
                confirmation_id=context.confirmation_id,
            )
            try:
                risk_result = self.risk_engine.evaluate(request)
            except Exception as exc:
                safety["risk"].update(
                    {"status": "error", "error_type": type(exc).__name__}
                )
                raise ToolLayerError(
                    RISK_ENGINE_ERROR,
                    "Risk Engine 适配器异常，已失败关闭。",
                ) from exc
            if not isinstance(risk_result, RiskEvaluationResult):
                safety["risk"]["status"] = "invalid_result"
                raise ToolLayerError(
                    RISK_ENGINE_ERROR,
                    "Risk Engine 返回了不符合契约的结果，已失败关闭。",
                )
            is_mock = risk_state["adapter_kind"] == "mock"
            safety["risk"].update(
                {
                    "status": "evaluated_mock" if is_mock else "evaluated",
                    "decision_id": risk_result.decision_id,
                    "risk_level": risk_result.risk_level,
                    "requires_confirmation": risk_result.requires_confirmation,
                    "requires_step_up": risk_result.requires_step_up,
                    "policy_version": risk_result.policy_version,
                    "reasons": list(risk_result.reasons),
                    "flags": list(risk_result.flags),
                }
            )
            if not risk_result.allowed:
                raise ToolLayerError(
                    RISK_DENIED,
                    "Risk Engine 拒绝了该工具调用。",
                    details={
                        "decision_id": risk_result.decision_id,
                        "reasons": list(risk_result.reasons),
                    },
                )
            if (
                risk_result.requires_confirmation
                and not context.confirmed
            ):
                raise ToolLayerError(
                    CONFIRMATION_REQUIRED,
                    "Risk Engine 要求用户确认后才能继续。",
                    details={"decision_id": risk_result.decision_id},
                )
            if risk_result.requires_step_up and not context.step_up_verified:
                raise ToolLayerError(
                    AUTH_INSUFFICIENT,
                    "Risk Engine 要求已核验的 step-up 认证，当前会话未提供。",
                    details={"decision_id": risk_result.decision_id},
                )

        production_checks = (
            safety["compliance"]["status"] == "evaluated"
            and (
                not definition.mutating
                or safety["risk"]["status"] == "evaluated"
            )
        )
        safety["production_checks_active"] = production_checks
        return safety

    # ------------------------------------------------------------------
    # Handler / evidence / errors
    # ------------------------------------------------------------------

    def _invoke_handler(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolCallContext,
        *,
        attempts_box: dict[str, int],
    ) -> dict[str, Any]:
        max_attempts = 1 if definition.mutating else max(definition.max_attempts, 1)
        last_error: ToolLayerError | None = None
        for attempt in range(1, max_attempts + 1):
            attempts_box["value"] = attempt
            try:
                return definition.handler(copy.deepcopy(arguments), context)
            except ToolLayerError as exc:
                last_error = exc
                if (
                    not definition.mutating
                    and exc.retryable
                    and attempt < max_attempts
                ):
                    safe_emit(
                        self.trace_sink,
                        {
                            "event": "tool_call_retry",
                            "trace_id": context.trace_id,
                            "tool": definition.name,
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "error_code": exc.code,
                        },
                    )
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise ToolLayerError(INTERNAL_ERROR, "工具执行未返回结果。")

    def _build_evidence(
        self,
        definition: ToolDefinition,
        data: dict[str, Any],
        call_id: str,
        trace_id: str,
    ) -> EvidenceItem:
        caveats: list[str] = []
        for key in (
            "assumptions",
            "limitations",
            "model_notes",
            "disclaimer",
            "notes",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                caveats.append(value.strip())
            elif isinstance(value, list):
                caveats.extend(
                    str(item).strip()
                    for item in value
                    if isinstance(item, str) and item.strip()
                )
        return EvidenceItem(
            tool=definition.name,
            tool_version=definition.version,
            call_id=call_id,
            trace_id=trace_id,
            sources=definition.data_sources,
            summary=(
                data.get("summary")
                if isinstance(data.get("summary"), str)
                else definition.description
            ),
            payload=copy.deepcopy(data),
            payload_hash=payload_hash(data),
            implementation_status=definition.implementation_status,
            simulated=definition.simulated,
            caveats=tuple(caveats[:12]),
        )

    def _error_result(
        self,
        *,
        definition: ToolDefinition | None,
        call_id: str,
        context: ToolCallContext,
        started_at: str,
        started_perf: float,
        meta: dict[str, Any],
        safety_meta: dict[str, Any],
        error: ToolErrorDetail,
        phase: str,
        attempts: int,
        force_unknown: bool = False,
    ) -> ToolCallResult:
        status = "unknown" if force_unknown else "error"
        if (
            definition is not None
            and definition.mutating
            and phase == "output_validation"
        ):
            status = "unknown"
        if (
            definition is not None
            and definition.mutating
            and phase == "handler"
            and error.code not in CONTROLLED_CODES
        ):
            status = "unknown"
        finished_at = now_iso()
        meta.update(
            {
                "finished_at": finished_at,
                "duration_ms": round(
                    (time.perf_counter() - started_perf) * 1000, 3
                ),
                "attempts": attempts,
                "phase": phase,
                "safety": copy.deepcopy(safety_meta),
                "duplicate": False,
                "mutation_outcome_unknown": status == "unknown",
            }
        )
        result = ToolCallResult(
            tool=definition.name if definition else str(meta.get("tool", "unknown")),
            version=(
                definition.version if definition else str(meta.get("version", "unknown"))
            ),
            call_id=call_id,
            ok=False,
            status=status,
            data={},
            error=error,
            meta=meta,
            evidence=None,
        )
        safe_emit(
            self.trace_sink,
            {
                "event": (
                    "tool_call_unknown"
                    if status == "unknown"
                    else (
                        "tool_call_failed"
                        if phase in {"handler", "output_validation"}
                        else "tool_call_rejected"
                    )
                ),
                "trace_id": context.trace_id,
                "call_id": call_id,
                "tool": definition.name if definition else meta.get("tool"),
                "status": status,
                "phase": phase,
                "error_code": error.code,
                "duration_ms": meta["duration_ms"],
                "safety": self._trace_safety(safety_meta),
            },
        )
        return result

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _base_meta(
        *, call_id: str, trace_id: str, started_at: str
    ) -> dict[str, Any]:
        return {
            "trace_id": trace_id,
            "call_id": call_id,
            "started_at": started_at,
            "finished_at": None,
            "duration_ms": 0.0,
            "mutating": False,
            "read_only": True,
            "risk_tier": "unknown",
            "permissions": [],
            "implementation_status": "unknown",
            "data_sources": [],
            "simulated": False,
            "duplicate": False,
            "attempts": 0,
            "phase": "lookup",
        }

    @staticmethod
    def _definition_meta(definition: ToolDefinition) -> dict[str, Any]:
        return {
            "tool": definition.name,
            "version": definition.version,
            "mutating": definition.mutating,
            "read_only": definition.read_only,
            "risk_tier": definition.risk_tier,
            "permissions": list(definition.permissions),
            "implementation_status": definition.implementation_status,
            "data_sources": list(definition.data_sources),
            "simulated": definition.simulated,
        }

    @staticmethod
    def _trace_safety(safety: dict[str, Any]) -> dict[str, Any]:
        return {
            "required": safety.get("required", False),
            "production_checks_active": safety.get(
                "production_checks_active", False
            ),
            "compliance_status": safety.get("compliance", {}).get("status"),
            "risk_status": safety.get("risk", {}).get("status"),
            "compliance_adapter_kind": safety.get("compliance", {}).get(
                "adapter_kind"
            ),
            "risk_adapter_kind": safety.get("risk", {}).get(
                "adapter_kind"
            ),
        }

    @staticmethod
    def _safe_hash(value: Any) -> str | None:
        try:
            return payload_hash(value)
        except Exception:
            return None
