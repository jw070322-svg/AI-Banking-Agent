"""Module 6 — Tool Calling Layer.

A self-contained unified tool registry, 13 banking/finance tools, validated
dispatch, sequential/conditional orchestration, evidence aggregation, report
generation, and explicit fail-closed ports for the existing Risk Engine and
Compliance Guard.

The completed modules under `bank_agent/risk/` and the legacy
`bank_agent.tools.ToolRegistry` are intentionally not modified. Use
`ToolRegistry` from this package for Module 6.
"""

from .adapters import (
    ComplianceEvaluationRequest,
    ComplianceEvaluationResult,
    ComplianceGuardAdapter,
    RiskEngineAdapter,
    RiskEvaluationRequest,
    RiskEvaluationResult,
    UnconfiguredComplianceGuardAdapter,
    UnconfiguredRiskEngineAdapter,
)
from .errors import ToolErrorDetail, ToolLayerError
from .mocks import MockComplianceGuardAdapter, MockRiskEngineAdapter
from .models import (
    EvidenceBundle,
    EvidenceItem,
    ToolCallContext,
    ToolCallResult,
    ToolDefinition,
)
from .orchestration import (
    OrchestrationResult,
    StepCondition,
    StepExecution,
    ToolOrchestrator,
    ToolPlan,
    ToolStep,
)
from .registry import ToolRegistry
from .reporting import MarkdownReportGenerator, generate_report, write_report
from .tracing import (
    CompositeTraceSink,
    InMemoryTraceSink,
    JsonlTraceSink,
    NullTraceSink,
    TraceSink,
)
from .services import (
    MockBankTransactionGateway,
    ProductCatalog,
    PolicyCorpus,
    ToolServices,
    TransactionGateway,
    TransactionRequest,
    UnavailableTransactionGateway,
)

__all__ = [
    "ComplianceEvaluationRequest",
    "ComplianceEvaluationResult",
    "ComplianceGuardAdapter",
    "CompositeTraceSink",
    "EvidenceBundle",
    "EvidenceItem",
    "InMemoryTraceSink",
    "JsonlTraceSink",
    "MarkdownReportGenerator",
    "NullTraceSink",
    "MockBankTransactionGateway",
    "MockComplianceGuardAdapter",
    "MockRiskEngineAdapter",
    "OrchestrationResult",
    "PolicyCorpus",
    "ProductCatalog",
    "RiskEngineAdapter",
    "RiskEvaluationRequest",
    "RiskEvaluationResult",
    "StepCondition",
    "StepExecution",
    "ToolCallContext",
    "ToolCallResult",
    "ToolDefinition",
    "ToolErrorDetail",
    "ToolLayerError",
    "ToolOrchestrator",
    "ToolPlan",
    "ToolRegistry",
    "ToolServices",
    "ToolStep",
    "TraceSink",
    "TransactionGateway",
    "TransactionRequest",
    "UnavailableTransactionGateway",
    "UnconfiguredComplianceGuardAdapter",
    "UnconfiguredRiskEngineAdapter",
    "generate_report",
    "write_report",
]
