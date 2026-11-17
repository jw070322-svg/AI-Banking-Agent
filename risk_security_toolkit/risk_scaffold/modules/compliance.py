"""Evaluate explicitly verified controls; documentation matches remain unknown."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ControlResult:
    control_id: str
    status: str


def check_controls(required: Iterable[str], verified: Mapping[str, bool]) -> list[ControlResult]:
    """The integration must validate reviewer, test evidence and expiry upstream.

    This scaffold aggregates supplied verification results; it does not establish
    legal compliance or accept repository keyword matches as verification.
    """
    if isinstance(required, str):
        raise ValueError("Required controls must be a collection, not a string")
    required = list(required)
    if not required or any(not isinstance(c, str) or not c.strip() for c in required):
        raise ValueError("At least one nonblank required control ID is needed")
    if len(required) != len(set(required)):
        raise ValueError("Required control IDs must be unique")
    if any(type(value) is not bool for value in verified.values()):
        raise ValueError("Verification results must be explicit booleans")
    return [ControlResult(c, "unknown" if c not in verified else "pass" if verified[c] else "fail")
            for c in required]
