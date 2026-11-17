"""Run with python -m examples.evaluate_controls from the toolkit directory."""
from dataclasses import asdict
import json

from risk_scaffold.modules.compliance import check_controls
from risk_scaffold.modules.risk_assessment import RiskAssessment
from risk_scaffold.modules.security import Principal, SecurityGate, ToolPolicy


def main():
    # Fictional demo policy: the project policy owner must approve real thresholds.
    risk = RiskAssessment(review_at=6, block_at=15, policy_version="fictional-demo-v1")
    gate = SecurityGate({"balance": ToolPolicy("account:read", "read"),
                         "transfer": ToolPolicy("account:write", "write")}, "fictional-demo-v1")
    # Replace this fixture with current server-verified identity and ownership.
    principal = Principal("demo-user", frozenset({"account:read", "account:write"}),
                          frozenset({"demo-account"}))
    print(json.dumps({
        "risk": asdict(risk.assess(likelihood=2, impact=3)),
        "compliance": [asdict(x) for x in check_controls(["resource_authorization", "audit"], {})],
        "read_gate": asdict(gate.check(principal, "balance", "demo-account")),
        "write_gate": asdict(gate.check(principal, "transfer", "demo-account")),
    }, indent=2))


if __name__ == "__main__":
    main()
