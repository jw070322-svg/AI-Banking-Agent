"""Minimal JSON audit events. Callers supply summaries, never raw business data."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re


def redact_text(value: str) -> str:
    value = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,})",
                   "[REDACTED]", value)
    value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)((?:token|password|secret|api[_-]?key)\s*[=:]\s*)[^\s&,;]+",
                   r"\1[REDACTED]", value)
    return value


@dataclass(frozen=True)
class AuditEvent:
    user_id: str
    intent: str
    tool: str
    input: str
    output: str
    risk_check: str
    approval: str
    timestamp: str

    @classmethod
    def now(cls, *, user_id: str, intent: str, tool: str, input: str, output: str,
            risk_check: str, approval: str) -> "AuditEvent":
        return cls(user_id, intent, tool, input, output, risk_check, approval,
                   datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, str]:
        if any(not isinstance(v, str) for v in asdict(self).values()):
            raise ValueError("Audit fields must be summary strings")
        return {k: redact_text(v) for k, v in asdict(self).items()}


def append_event(path: Path, event: AuditEvent):
    """Local development sink; production needs an access-controlled durable sink.

    Redaction is a secondary safeguard, not a complete secret or PII detector.
    A sink failure propagates so the caller cannot silently lose an event.
    """
    payload = event.to_dict()
    if path.is_symlink():
        raise ValueError("Audit log must not be a symlink")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
