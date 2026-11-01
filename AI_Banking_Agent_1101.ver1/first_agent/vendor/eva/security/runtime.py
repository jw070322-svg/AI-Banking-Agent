"""Explicit server-side assembly of Module 6 and 8; no import-time actions."""
from dataclasses import dataclass
from pathlib import Path

from ..tool_calling.hardening import HardenedToolRegistry
from ..tool_calling.services import ToolServices
from .audit import JsonlSecurityAudit, SecurityAuditLogger
from .auth import MockAuthenticationProvider
from .authorization import AuthorizationService
from .hardening import HardenedToolGateway, LockedConfirmationService
from .injection import OutputGuard, PromptInjectionGuard
from .resources import MockBankResourceResolver
from .compatibility import CompatibleScanner


@dataclass
class SecurityRuntime:
    registry: HardenedToolRegistry
    gateway: HardenedToolGateway
    auth: object
    audit: SecurityAuditLogger


def build_runtime(directory, *, users=(), auth_provider=None, services=None,
                  risk_engine=None, compliance_guard=None, step_up_verifier=None):
    """Compose compatible ports. Default data/identity remain explicit demos.

    No auto-enable of mock safety or real payments. Production adapters remain
    unverified unless independently configured; missing R4 controls deny calls.
    Do not expose registry/auth administration to a model or browser client.
    """
    directory = Path(directory)
    services = services if services is not None else ToolServices.demo()
    scanner = CompatibleScanner()
    audit = SecurityAuditLogger(JsonlSecurityAudit(directory / 'security-audit', scanner=scanner), scanner=scanner)
    auth = auth_provider if auth_provider is not None else MockAuthenticationProvider(users, audit=audit)
    registry = HardenedToolRegistry(services, journal_path=directory / 'tool-dispatch.sqlite3',
        risk_engine=risk_engine, compliance_guard=compliance_guard)
    resolver = MockBankResourceResolver(services.bank, services.planning)
    guard = PromptInjectionGuard(scanner)
    confirmation = LockedConfirmationService(audit=audit, step_up_verifier=step_up_verifier)
    gateway = HardenedToolGateway(registry, auth, AuthorizationService(resolver),
        injection_guard=guard, confirmation=confirmation,
        output_guard=OutputGuard(guard, resolver=resolver), audit=audit)
    return SecurityRuntime(registry, gateway, auth, audit)
