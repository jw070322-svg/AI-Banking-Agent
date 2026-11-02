"""Module 8 — Security.

Authentication, authorization, prompt-injection protection and
transaction-bound confirmation, integrated with the existing agent pipeline and
Module 6 Tool Registry through composition. The completed Risk Engine and
Compliance Guard are not modified or re-implemented.

Quick entry points:
- `MockAuthenticationProvider` — development-only identity/session provider.
- `AuthorizationService` + `MockBankResourceResolver` — RBAC + ownership.
- `PromptInjectionGuard` / `OutputGuard` — screening and output filtering.
- `ConfirmationService` — transaction-bound, single-use confirmations.
- `AuthorizedToolGateway` — wraps `ToolRegistry.execute`.
- `SecureAgentGateway` — wraps `BankingAgent.handle`.
- `ExistingComplianceGuardAdapter` / `ExistingRiskEngineAdapter` — prepared
  bridges to the completed modules (not verified for production).
"""

from .adapters import (
    ExistingComplianceGuardAdapter,
    ExistingRiskEngineAdapter,
    RiskAuthorizationEvidence,
    RiskAuthorizationRegistry,
)
from .audit import (
    AuditUnavailableError,
    InMemorySecurityAudit,
    JsonlSecurityAudit,
    NullSecurityAudit,
    SecurityAuditLogger,
    SecurityAuditSink,
)
from .auth import (
    AuthenticationProvider,
    Credentials,
    MockAuthenticationProvider,
    UserSeed,
)
from .authorization import (
    ACTIONS,
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    TOOL_ACTIONS,
    AccessGrant,
    ActionDefinition,
    AuthorizationService,
    InMemoryAccessGrantStore,
    Permission,
    actions_for_tool,
    permissions_for_roles,
)
from .confirmation import (
    ConfirmationChallenge,
    ConfirmationService,
    StepUpVerifier,
    TransactionSecurityLimits,
    TransactionSecurityPolicy,
)
from .gateway import (
    AuthorizedToolGateway,
    SecureAgentGateway,
    SecureAgentResponse,
    SecureToolResult,
)
from .injection import (
    OutputGuard,
    OutputValidation,
    PromptInjectionGuard,
    ScreeningResult,
    ToolOutputValidation,
)
from .models import (
    SECURITY_POLICY_VERSION,
    AuthSession,
    Decision,
    LoginResult,
    Principal,
    ReasonCode,
    ResolvedResource,
    ResourceRef,
    SecurityCategory,
    SecurityDecision,
    SecurityEvent,
    SecurityFinding,
    SessionValidation,
    fail_closed,
)
from .passwords import PasswordRecord, hash_password, verify_password
from .resources import MockBankResourceResolver, ResourceResolver
from .sessions import (
    InMemorySessionStore,
    SessionCookiePolicy,
    SessionPolicy,
    SessionRecord,
    SessionStore,
    hash_token,
)

__all__ = [
    "ACTIONS",
    "ALL_PERMISSIONS",
    "AccessGrant",
    "ActionDefinition",
    "AuditUnavailableError",
    "AuthSession",
    "AuthenticationProvider",
    "AuthorizationService",
    "AuthorizedToolGateway",
    "ConfirmationChallenge",
    "ConfirmationService",
    "Credentials",
    "Decision",
    "ExistingComplianceGuardAdapter",
    "ExistingRiskEngineAdapter",
    "InMemoryAccessGrantStore",
    "InMemorySecurityAudit",
    "InMemorySessionStore",
    "JsonlSecurityAudit",
    "LoginResult",
    "MockAuthenticationProvider",
    "MockBankResourceResolver",
    "NullSecurityAudit",
    "OutputGuard",
    "OutputValidation",
    "PasswordRecord",
    "Permission",
    "Principal",
    "PromptInjectionGuard",
    "ROLE_PERMISSIONS",
    "ReasonCode",
    "ResolvedResource",
    "ResourceRef",
    "ResourceResolver",
    "RiskAuthorizationEvidence",
    "RiskAuthorizationRegistry",
    "SECURITY_POLICY_VERSION",
    "ScreeningResult",
    "SecureAgentGateway",
    "SecureAgentResponse",
    "SecureToolResult",
    "SecurityAuditLogger",
    "SecurityAuditSink",
    "SecurityCategory",
    "SecurityDecision",
    "SecurityEvent",
    "SecurityFinding",
    "SessionCookiePolicy",
    "SessionPolicy",
    "SessionRecord",
    "SessionStore",
    "SessionValidation",
    "StepUpVerifier",
    "TOOL_ACTIONS",
    "ToolOutputValidation",
    "TransactionSecurityLimits",
    "TransactionSecurityPolicy",
    "UserSeed",
    "actions_for_tool",
    "fail_closed",
    "hash_password",
    "hash_token",
    "permissions_for_roles",
    "verify_password",
]
