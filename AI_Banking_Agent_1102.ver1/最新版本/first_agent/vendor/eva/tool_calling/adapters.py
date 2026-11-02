"""Integration ports for the completed Risk Engine and Compliance Guard.

These are deliberately *ports only*. Module 6 does not import or reimplement
the completed modules under `bank_agent/risk/`. The registry calls these ports
at the documented lifecycle points when an adapter is injected.

Readiness contract for a production adapter:
  - is_connected = True
  - is_verified = True
  - adapter_kind = "production"

A mock adapter (`adapter_kind="mock"`, `is_verified=False`) is never enabled by
default. Tests must opt in with `allow_mock_safety=True`, and every result then
records that mock safety checks ran. This prevents a placeholder or test double
from being presented as the completed production control.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..models import new_id, utc_now
from .errors import AdapterNotConnectedError


@dataclass(frozen=True)
class RiskEvaluationRequest:
    """Input contract for an adapter around the existing Risk Engine.

    A future bridge can translate this single-tool request into the existing
    engine's plan/preview/confirm/authorize lifecycle. For state-changing tools
    Module 6 calls this after parameter validation and explicit confirmation,
    and before the handler executes.
    """

    request_id: str
    trace_id: str
    user_id: str
    session_id: str
    tool_name: str
    tool_version: str
    mutating: bool
    risk_tier: str
    permissions: tuple[str, ...]
    arguments: Mapping[str, Any]
    request_text: str
    auth_level: str
    confirmation_id: str | None = None


@dataclass(frozen=True)
class RiskEvaluationResult:
    allowed: bool
    decision_id: str
    risk_level: str = "unknown"
    requires_confirmation: bool = False
    requires_step_up: bool = False
    reasons: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    policy_version: str | None = None
    evaluated_at: str = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComplianceEvaluationRequest:
    """Input contract for an adapter around the existing Compliance Guard.

    `request_text` is the user's natural-language request; `arguments` is the
    already-schema-validated tool input. The guard decides whether the call may
    proceed. Findings are copied into metadata and evidence, never executed.
    """

    request_id: str
    trace_id: str
    user_id: str
    session_id: str
    tool_name: str
    tool_version: str
    request_text: str
    arguments: Mapping[str, Any]
    phase: str = "pre_execution"


@dataclass(frozen=True)
class ComplianceEvaluationResult:
    allowed: bool
    decision_id: str
    findings: tuple[Mapping[str, Any], ...] = ()
    reasons: tuple[str, ...] = ()
    policy_version: str | None = None
    evaluated_at: str = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class RiskEngineAdapter(ABC):
    """Port implemented by a bridge to the completed Risk Engine."""

    adapter_name = "Risk Engine"
    adapter_kind = "unconfigured"
    is_connected = False
    is_verified = False
    description = "Placeholder only; the completed Risk Engine is not connected."

    def readiness(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter_name,
            "adapter_kind": self.adapter_kind,
            "is_connected": self.is_connected,
            "is_verified": self.is_verified,
            "description": self.description,
        }

    @abstractmethod
    def evaluate(self, request: RiskEvaluationRequest) -> RiskEvaluationResult:
        raise NotImplementedError


class ComplianceGuardAdapter(ABC):
    """Port implemented by a bridge to the completed Compliance Guard."""

    adapter_name = "Compliance Guard"
    adapter_kind = "unconfigured"
    is_connected = False
    is_verified = False
    description = "Placeholder only; the completed Compliance Guard is not connected."

    def readiness(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter_name,
            "adapter_kind": self.adapter_kind,
            "is_connected": self.is_connected,
            "is_verified": self.is_verified,
            "description": self.description,
        }

    @abstractmethod
    def evaluate(
        self, request: ComplianceEvaluationRequest
    ) -> ComplianceEvaluationResult:
        raise NotImplementedError


class UnconfiguredRiskEngineAdapter(RiskEngineAdapter):
    """Default fail-closed placeholder for the existing Risk Engine."""

    def evaluate(self, request: RiskEvaluationRequest) -> RiskEvaluationResult:
        raise AdapterNotConnectedError("existing Risk Engine adapter")


class UnconfiguredComplianceGuardAdapter(ComplianceGuardAdapter):
    """Default fail-closed placeholder for the existing Compliance Guard."""

    def evaluate(
        self, request: ComplianceEvaluationRequest
    ) -> ComplianceEvaluationResult:
        raise AdapterNotConnectedError("existing Compliance Guard adapter")


def new_safety_request_id() -> str:
    return new_id("SAFE")
