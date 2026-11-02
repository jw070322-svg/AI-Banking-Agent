"""Explicit test doubles for Module 6 safety ports.

TEST ONLY. These classes are not the completed Risk Engine or Compliance
Guard, do not implement their rules, and are never enabled by the registry
unless the caller sets `allow_mock_safety=True`. Their results are labelled
`evaluated_mock`, never `verified`.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..models import new_id
from .adapters import (
    ComplianceEvaluationRequest,
    ComplianceEvaluationResult,
    ComplianceGuardAdapter,
    RiskEngineAdapter,
    RiskEvaluationRequest,
    RiskEvaluationResult,
)


class MockRiskEngineAdapter(RiskEngineAdapter):
    """TEST ONLY configurable gate; not a risk decision implementation."""

    adapter_name = "Mock Risk Engine Adapter (TEST ONLY)"
    adapter_kind = "mock"
    is_connected = True
    is_verified = False
    description = (
        "Configurable test double. It does not implement the completed Risk "
        "Engine and must never be used outside tests/demos."
    )

    def __init__(
        self,
        *,
        deny_all: bool = False,
        deny_tools: Iterable[str] = (),
        require_confirmation: bool = False,
        require_step_up: bool = False,
    ) -> None:
        self.deny_all = deny_all
        self.deny_tools = frozenset(deny_tools)
        self.require_confirmation = require_confirmation
        self.require_step_up = require_step_up
        self.calls: list[RiskEvaluationRequest] = []

    def evaluate(self, request: RiskEvaluationRequest) -> RiskEvaluationResult:
        self.calls.append(request)
        denied = self.deny_all or request.tool_name in self.deny_tools
        return RiskEvaluationResult(
            allowed=not denied,
            decision_id=new_id("MOCKRISK"),
            risk_level="high" if request.mutating else "low",
            requires_confirmation=self.require_confirmation,
            requires_step_up=self.require_step_up,
            reasons=(
                ("mock policy denied this tool",) if denied else ()
            ),
            flags=("mock_adapter",),
        )


class MockComplianceGuardAdapter(ComplianceGuardAdapter):
    """TEST ONLY configurable gate; it performs no compliance analysis."""

    adapter_name = "Mock Compliance Guard Adapter (TEST ONLY)"
    adapter_kind = "mock"
    is_connected = True
    is_verified = False
    description = (
        "Configurable test double. It does not implement the completed "
        "Compliance Guard and must never be used outside tests/demos."
    )

    def __init__(
        self,
        *,
        deny_all: bool = False,
        deny_tools: Iterable[str] = (),
        findings: Iterable[dict[str, Any]] = (),
    ) -> None:
        self.deny_all = deny_all
        self.deny_tools = frozenset(deny_tools)
        self.findings = tuple(dict(item) for item in findings)
        self.calls: list[ComplianceEvaluationRequest] = []

    def evaluate(
        self, request: ComplianceEvaluationRequest
    ) -> ComplianceEvaluationResult:
        self.calls.append(request)
        denied = self.deny_all or request.tool_name in self.deny_tools
        return ComplianceEvaluationResult(
            allowed=not denied,
            decision_id=new_id("MOCKCOMP"),
            findings=(
                self.findings
                if self.findings
                else (
                    {
                        "code": "MOCK_ADAPTER_ONLY",
                        "severity": "info",
                        "detail": "No compliance logic ran; this is a test double.",
                    },
                )
            ),
            reasons=(
                ("mock compliance gate denied this tool",) if denied else ()
            ),
        )
