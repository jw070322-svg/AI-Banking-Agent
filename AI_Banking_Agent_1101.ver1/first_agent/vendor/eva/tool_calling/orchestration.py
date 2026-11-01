"""Sequential and conditional orchestration for tool-call plans.

The orchestrator is deliberately separate from the Tool Registry. Plans are
declarative and contain no executable expressions: arguments reference prior
results, conditions use a fixed operator allowlist, and dependency cycles are
rejected before any tool is called.
"""

from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from ..models import new_id
from .errors import ToolErrorDetail
from .models import (
    EvidenceBundle,
    ToolCallContext,
    ToolCallResult,
)
from .tracing import InMemoryTraceSink, TraceSink, safe_emit
from .utils import deep_copy_json, now_iso, payload_hash


_REF_RE = re.compile(
    r"^\$\{([A-Za-z0-9_-]+)(?:\.([A-Za-z0-9_.-]+))?\}$"
)
_REF_SCAN_RE = re.compile(
    r"\$\{([A-Za-z0-9_-]+)(?:\.([A-Za-z0-9_.-]+))?\}"
)
_STEP_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_OPERATORS = frozenset(
    {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "exists", "truthy"}
)
_MISSING = object()


@dataclass(frozen=True)
class StepCondition:
    """A safe condition over a prior step's `data` payload."""

    step_id: str
    path: str = ""
    operator: str = "exists"
    value: Any = None

    def __post_init__(self) -> None:
        if self.operator not in _OPERATORS:
            raise ValueError(f"unsupported condition operator: {self.operator}")


@dataclass(frozen=True)
class ToolStep:
    step_id: str
    tool: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    condition: StepCondition | None = None
    optional: bool = False
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", copy.deepcopy(dict(self.arguments)))
        object.__setattr__(self, "depends_on", tuple(self.depends_on))


@dataclass
class ToolPlan:
    goal: str
    steps: tuple[ToolStep, ...] | list[ToolStep]
    context: ToolCallContext
    plan_id: str = field(default_factory=lambda: new_id("PLAN"))
    # Confirmations are per-step and cannot be supplied through tool arguments.
    confirmations: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "confirmations", dict(self.confirmations))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass
class StepExecution:
    step_id: str
    tool: str
    label: str
    status: str  # success / error / unknown / skipped / blocked / not_run
    result: ToolCallResult | None = None
    skip_reason: str | None = None
    skip_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "label": self.label,
            "status": self.status,
            "skip_reason": self.skip_reason,
            "skip_detail": self.skip_detail,
            "result": self.result.to_dict() if self.result is not None else None,
        }


@dataclass
class OrchestrationResult:
    plan_id: str
    trace_id: str
    goal: str
    status: str
    steps: list[StepExecution]
    evidence: EvidenceBundle
    errors: list[dict[str, Any]]
    validation_errors: list[dict[str, Any]]
    started_at: str
    finished_at: str
    duration_ms: float
    trace: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful_results(self) -> list[ToolCallResult]:
        return [
            step.result
            for step in self.steps
            if step.status == "success" and step.result is not None
        ]

    @property
    def success_count(self) -> int:
        return sum(1 for step in self.steps if step.status == "success")

    @property
    def skipped_count(self) -> int:
        return sum(1 for step in self.steps if step.status == "skipped")

    @property
    def error_count(self) -> int:
        return sum(
            1
            for step in self.steps
            if step.status in {"error", "unknown", "blocked"}
        )

    @property
    def summary(self) -> str:
        return (
            f"计划共 {len(self.steps)} 步：成功 {self.success_count}，"
            f"跳过 {self.skipped_count}，异常 {self.error_count}。"
        )

    def to_dict(self, *, include_trace: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "plan_id": self.plan_id,
            "trace_id": self.trace_id,
            "goal": self.goal,
            "status": self.status,
            "summary": self.summary,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "steps": [step.to_dict() for step in self.steps],
            "evidence": self.evidence.to_dict(),
            "errors": deep_copy_json(self.errors),
            "validation_errors": deep_copy_json(self.validation_errors),
            "metadata": deep_copy_json(self.metadata),
        }
        if include_trace:
            payload["trace"] = deep_copy_json(self.trace)
        return payload


class _ResolutionError(Exception):
    pass


class ToolOrchestrator:
    """Executes a ToolPlan against a ToolRegistry."""

    def __init__(
        self,
        registry: Any,
        *,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self.registry = registry
        self.trace_sink = trace_sink or getattr(
            registry, "trace_sink", None
        ) or InMemoryTraceSink()

    def run(self, plan: ToolPlan) -> OrchestrationResult:
        if not isinstance(plan, ToolPlan):
            raise TypeError("run() requires a ToolPlan")
        if not isinstance(plan.context, ToolCallContext):
            raise TypeError("ToolPlan.context must be a ToolCallContext")
        trace_id = plan.context.trace_id
        started_at = now_iso()
        started_perf = time.perf_counter()
        self._trace(
            {
                "event": "plan_started",
                "trace_id": trace_id,
                "plan_id": plan.plan_id,
                "goal_hash": payload_hash({"goal": plan.goal}),
                "step_count": len(plan.steps),
            }
        )

        validation_errors = self._validate(plan)
        if validation_errors:
            steps = [
                StepExecution(
                    step_id=step.step_id,
                    tool=step.tool,
                    label=step.label or step.tool,
                    status="not_run",
                )
                for step in plan.steps
            ]
            errors = [
                {
                    "step_id": item.get("step_id"),
                    "code": "PLAN_INVALID",
                    "message": item["message"],
                    "retryable": False,
                }
                for item in validation_errors
            ]
            finished_at = now_iso()
            duration = round((time.perf_counter() - started_perf) * 1000, 3)
            self._trace(
                {
                    "event": "plan_finished",
                    "trace_id": trace_id,
                    "plan_id": plan.plan_id,
                    "status": "failed",
                    "duration_ms": duration,
                    "validation_error_count": len(validation_errors),
                }
            )
            return OrchestrationResult(
                plan_id=plan.plan_id,
                trace_id=trace_id,
                goal=plan.goal,
                status="failed",
                steps=steps,
                evidence=EvidenceBundle(),
                errors=errors,
                validation_errors=validation_errors,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration,
                trace=self._trace_for(trace_id),
            )

        refs_by_step = {
            step.step_id: sorted(self._collect_references(step.arguments))
            for step in plan.steps
        }
        outcomes: list[StepExecution] = [
            StepExecution(
                step_id=step.step_id,
                tool=step.tool,
                label=step.label or step.tool,
                status="not_run",
            )
            for step in plan.steps
        ]
        results_by_step: dict[str, ToolCallResult] = {}
        outcomes_by_step: dict[str, StepExecution] = {}
        errors: list[dict[str, Any]] = []
        evidence = EvidenceBundle()
        required_failure = False
        unknown_outcome = False

        for index, step in enumerate(plan.steps):
            if required_failure or unknown_outcome:
                break
            outcome = outcomes[index]

            condition_ok, condition_reason = self._evaluate_condition(
                step.condition, results_by_step, outcomes_by_step
            )
            if not condition_ok:
                outcome.status = "skipped"
                outcome.skip_reason = condition_reason
                outcome.skip_detail = self._condition_detail(step.condition)
                outcomes_by_step[step.step_id] = outcome
                self._trace(
                    {
                        "event": "plan_step_skipped",
                        "trace_id": trace_id,
                        "plan_id": plan.plan_id,
                        "step_id": step.step_id,
                        "tool": step.tool,
                        "reason": condition_reason,
                    }
                )
                continue

            dependency_ids = list(step.depends_on) + list(refs_by_step[step.step_id])
            failed_dependency = next(
                (
                    dependency
                    for dependency in dependency_ids
                    if outcomes_by_step.get(dependency) is None
                    or outcomes_by_step[dependency].status
                    not in {"success"}
                ),
                None,
            )
            if failed_dependency is not None:
                if step.optional:
                    outcome.status = "skipped"
                    outcome.skip_reason = "dependency_not_satisfied"
                    outcome.skip_detail = failed_dependency
                else:
                    # A required step cannot silently disappear because an
                    # upstream branch was skipped/failed. Surface it as blocked.
                    outcome.status = "blocked"
                    outcome.skip_reason = "dependency_not_satisfied"
                    outcome.skip_detail = failed_dependency
                    errors.append(
                        {
                            "step_id": step.step_id,
                            "code": "DEPENDENCY_FAILED",
                            "message": (
                                f"步骤「{step.step_id}」依赖的「{failed_dependency}」"
                                "未成功，已阻止执行。"
                            ),
                            "retryable": False,
                        }
                    )
                    required_failure = True
                outcomes_by_step[step.step_id] = outcome
                self._trace(
                    {
                        "event": "plan_step_skipped",
                        "trace_id": trace_id,
                        "plan_id": plan.plan_id,
                        "step_id": step.step_id,
                        "tool": step.tool,
                        "reason": outcome.skip_reason or "dependency_not_satisfied",
                        "dependency": failed_dependency,
                    }
                )
                continue

            try:
                resolved = self._resolve_arguments(
                    step.arguments, results_by_step
                )
            except _ResolutionError as exc:
                error = {
                    "step_id": step.step_id,
                    "code": "ARGUMENT_RESOLUTION_FAILED",
                    "message": str(exc),
                    "retryable": False,
                }
                errors.append(error)
                outcome.status = "error" if not step.optional else "skipped"
                if step.optional:
                    outcome.skip_reason = "argument_resolution_failed"
                    outcome.skip_detail = str(exc)
                if not step.optional:
                    required_failure = True
                outcomes_by_step[step.step_id] = outcome
                self._trace(
                    {
                        "event": "plan_step_failed",
                        "trace_id": trace_id,
                        "plan_id": plan.plan_id,
                        "step_id": step.step_id,
                        "code": "ARGUMENT_RESOLUTION_FAILED",
                    }
                )
                continue

            confirmation_id = plan.confirmations.get(step.step_id)
            step_context = replace(
                plan.context,
                confirmed=bool(confirmation_id),
                confirmation_id=confirmation_id,
                idempotency_key=(
                    f"{plan.plan_id}:{step.step_id}"
                    if self._is_mutating(step.tool)
                    else None
                ),
                metadata={
                    **dict(plan.context.metadata),
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                },
            )
            self._trace(
                {
                    "event": "plan_step_started",
                    "trace_id": trace_id,
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "arguments_hash": payload_hash(resolved),
                    "confirmed": bool(confirmation_id),
                }
            )
            result = self.registry.execute(
                step.tool, resolved, step_context
            )
            outcome.result = result
            results_by_step[step.step_id] = result
            outcomes_by_step[step.step_id] = outcome

            if result.ok:
                outcome.status = "success"
                if result.evidence is not None:
                    evidence.add(result.evidence)
                self._trace(
                    {
                        "event": "plan_step_finished",
                        "trace_id": trace_id,
                        "plan_id": plan.plan_id,
                        "step_id": step.step_id,
                        "tool": step.tool,
                        "status": "success",
                        "duration_ms": result.meta.get("duration_ms"),
                    }
                )
                continue

            outcome.status = "unknown" if result.status == "unknown" else "error"
            error_payload = {
                "step_id": step.step_id,
                "code": result.error_code or "TOOL_EXECUTION_FAILED",
                "message": (
                    result.error.message if result.error else "工具执行失败。"
                ),
                "retryable": bool(result.error.retryable) if result.error else False,
                "mutation_outcome_unknown": result.status == "unknown",
            }
            errors.append(error_payload)
            if result.status == "unknown":
                unknown_outcome = True
            elif not step.optional:
                required_failure = True
            self._trace(
                {
                    "event": "plan_step_finished",
                    "trace_id": trace_id,
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "status": outcome.status,
                    "error_code": error_payload["code"],
                }
            )

        if unknown_outcome:
            plan_status = "unknown"
        elif required_failure or errors:
            plan_status = (
                "partially_completed" if any(
                    step.status == "success" for step in outcomes
                ) else "failed"
            )
        else:
            plan_status = "completed"

        finished_at = now_iso()
        duration = round((time.perf_counter() - started_perf) * 1000, 3)
        self._trace(
            {
                "event": "plan_finished",
                "trace_id": trace_id,
                "plan_id": plan.plan_id,
                "status": plan_status,
                "duration_ms": duration,
                "success_count": sum(
                    1 for step in outcomes if step.status == "success"
                ),
                "error_count": len(errors),
            }
        )
        result = OrchestrationResult(
            plan_id=plan.plan_id,
            trace_id=trace_id,
            goal=plan.goal,
            status=plan_status,
            steps=outcomes,
            evidence=evidence,
            errors=errors,
            validation_errors=[],
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration,
            trace=self._trace_for(trace_id),
            metadata=dict(plan.metadata),
        )
        return result

    execute = run

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, plan: ToolPlan) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if not plan.steps:
            errors.append(
                {
                    "step_id": None,
                    "message": "plan must contain at least one step",
                }
            )
            return errors
        seen: dict[str, int] = {}
        for index, step in enumerate(plan.steps):
            if not _STEP_ID_RE.fullmatch(step.step_id):
                errors.append(
                    {
                        "step_id": step.step_id,
                        "message": "step_id must be an identifier",
                    }
                )
            if step.step_id in seen:
                errors.append(
                    {
                        "step_id": step.step_id,
                        "message": "duplicate step_id",
                    }
                )
            if step.tool not in self.registry:
                errors.append(
                    {
                        "step_id": step.step_id,
                        "message": f"unregistered tool: {step.tool}",
                    }
                )
            for dependency in step.depends_on:
                if dependency not in seen:
                    errors.append(
                        {
                            "step_id": step.step_id,
                            "message": (
                                f"dependency must reference an earlier step: {dependency}"
                            ),
                        }
                    )
            if step.condition is not None:
                if step.condition.operator not in _OPERATORS:
                    errors.append(
                        {
                            "step_id": step.step_id,
                            "message": "unsupported condition operator",
                        }
                    )
                if step.condition.step_id not in seen:
                    errors.append(
                        {
                            "step_id": step.step_id,
                            "message": (
                                "condition must reference an earlier step: "
                                f"{step.condition.step_id}"
                            ),
                        }
                    )
            for referenced in self._collect_references(step.arguments):
                if referenced not in seen:
                    errors.append(
                        {
                            "step_id": step.step_id,
                            "message": (
                                "argument reference must target an earlier step: "
                                f"{referenced}"
                            ),
                        }
                    )
            seen[step.step_id] = index
        return errors

    # ------------------------------------------------------------------
    # References / conditions
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_references(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, str):
            match = _REF_RE.fullmatch(value)
            if match:
                found.add(match.group(1))
        elif isinstance(value, Mapping):
            for item in value.values():
                found.update(ToolOrchestrator._collect_references(item))
        elif isinstance(value, (list, tuple)):
            for item in value:
                found.update(ToolOrchestrator._collect_references(item))
        return found

    @staticmethod
    def _resolve_path(value: Any, path: str) -> Any:
        if not path:
            return value
        current = value
        for segment in path.split("."):
            if isinstance(current, Mapping):
                if segment not in current:
                    return _MISSING
                current = current[segment]
            elif isinstance(current, list):
                try:
                    index = int(segment)
                except ValueError:
                    return _MISSING
                if index < 0 or index >= len(current):
                    return _MISSING
                current = current[index]
            else:
                return _MISSING
        return current

    def _resolve_arguments(
        self,
        value: Any,
        results_by_step: Mapping[str, ToolCallResult],
    ) -> Any:
        if isinstance(value, str):
            match = _REF_RE.fullmatch(value)
            if not match:
                return value
            step_id, path = match.group(1), match.group(2) or ""
            result = results_by_step.get(step_id)
            if result is None or not result.ok:
                raise _ResolutionError(
                    f"referenced step {step_id} has no successful result"
                )
            resolved = self._resolve_path(result.data, path)
            if resolved is _MISSING:
                raise _ResolutionError(
                    f"referenced field is missing: {step_id}.{path}"
                )
            return copy.deepcopy(resolved)
        if isinstance(value, Mapping):
            return {
                key: self._resolve_arguments(item, results_by_step)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._resolve_arguments(item, results_by_step)
                for item in value
            ]
        return value

    def _evaluate_condition(
        self,
        condition: StepCondition | None,
        results_by_step: Mapping[str, ToolCallResult],
        outcomes_by_step: Mapping[str, StepExecution],
    ) -> tuple[bool, str | None]:
        if condition is None:
            return True, None
        dependency = outcomes_by_step.get(condition.step_id)
        if dependency is None or dependency.status != "success":
            return False, "condition_dependency_unavailable"
        result = results_by_step.get(condition.step_id)
        if result is None or not result.ok:
            return False, "condition_dependency_unavailable"
        left = self._resolve_path(result.data, condition.path)
        if left is _MISSING:
            return False, "condition_path_missing"
        if condition.operator == "exists":
            return True, None
        if condition.operator == "truthy":
            return bool(left), None
        matched = self._compare(condition.operator, left, condition.value)
        return matched, None if matched else "condition_not_met"

    @staticmethod
    def _compare(operator: str, left: Any, right: Any) -> bool:
        if operator == "eq":
            return ToolOrchestrator._normalized_equal(left, right)
        if operator == "ne":
            return not ToolOrchestrator._normalized_equal(left, right)
        if operator in {"gt", "gte", "lt", "lte"}:
            left_number = ToolOrchestrator._maybe_decimal(left)
            right_number = ToolOrchestrator._maybe_decimal(right)
            if left_number is None or right_number is None:
                return False
            if operator == "gt":
                return left_number > right_number
            if operator == "gte":
                return left_number >= right_number
            if operator == "lt":
                return left_number < right_number
            return left_number <= right_number
        if operator == "contains":
            if isinstance(left, (list, tuple, set)):
                return right in left
            if isinstance(left, Mapping):
                return right in left
            if isinstance(left, str):
                return str(right) in left
            return False
        if operator == "in":
            if isinstance(right, (list, tuple, set)):
                return left in right
            if isinstance(right, str):
                return isinstance(left, str) and left in right
            if isinstance(right, Mapping):
                return left in right
            return False
        return False

    @staticmethod
    def _normalized_equal(left: Any, right: Any) -> bool:
        if isinstance(left, bool) or isinstance(right, bool):
            return left is right
        left_number = ToolOrchestrator._maybe_decimal(left)
        right_number = ToolOrchestrator._maybe_decimal(right)
        if left_number is not None and right_number is not None:
            return left_number == right_number
        return left == right

    @staticmethod
    def _maybe_decimal(value: Any) -> Decimal | None:
        if isinstance(value, bool):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _is_mutating(self, tool: str) -> bool:
        try:
            return bool(self.registry.get(tool).mutating)
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Trace
    # ------------------------------------------------------------------

    def _trace(self, event: dict[str, Any]) -> None:
        safe_emit(self.trace_sink, event)

    def _trace_for(self, trace_id: str) -> list[dict[str, Any]]:
        getter = getattr(self.trace_sink, "for_trace", None)
        if callable(getter):
            return getter(trace_id)
        events = getattr(self.trace_sink, "events", None)
        if callable(events):
            return [
                event
                for event in events()
                if event.get("trace_id") == trace_id
            ]
        return []

    @staticmethod
    def _condition_detail(condition: StepCondition | None) -> str | None:
        if condition is None:
            return None
        return (
            f"{condition.step_id}.{condition.path or '$'} "
            f"{condition.operator} {condition.value!r}"
        )
