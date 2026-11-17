"""Deterministic candidate requirements; matches do not prove implementation."""
from __future__ import annotations

from dataclasses import asdict
import re

from .documentation import extract
from .modules.audit import redact_text
from .sources import Corpus


CONTROLS = (
    ("risk_assessment", "risk_assessment.py", r"\brisk\b|风险|风控",
     "Which risk taxonomy, scoring scale, thresholds and policy owner are approved?"),
    ("compliance_evidence", "compliance.py", r"\bcompliance\b|合规|证据",
     "Which jurisdictions, obligations, control IDs, reviewers and evidence expiry rules apply?"),
    ("resource_authorization", "security.py", r"\bauthoriz\w*|\bpermission\w*|权限|授权",
     "Which identity provider, resource ownership checks and tool scopes are authoritative?"),
    ("bound_confirmation", "security.py", r"\bconfirm\w*|\bapproval\b|确认|审批",
     "How are confirmations bound to principal, exact parameters, policy version and expiry?"),
    ("audit_trail", "audit.py", r"\baudit\w*|审计|日志",
     "What are log retention, access, redaction, event IDs and integrity requirements?"),
    ("untrusted_content", "security.py", r"\binjection\b|提示注入|外部内容|外部文本",
     "Which adversarial cases verify that retrieved content cannot grant tool permissions?"),
)


def make_plan(corpus: Corpus) -> dict:
    sections, warnings = [], list(corpus.warnings)
    for document in corpus.documents:
        try:
            sections.extend(extract(document))
        except (SyntaxError, ValueError, RecursionError):
            warnings.append(f"Could not parse Python docstrings: {document.path}")
    controls = []
    for control_id, module, pattern, question in CONTROLS:
        matches = []
        for section in sections:
            for number, line in section.lines:
                if re.search(pattern, line, re.IGNORECASE):
                    matches.append({"path": section.document.path, "line": number,
                                    "section": redact_text(section.title),
                                    "excerpt": redact_text(line.strip())[:240],
                                    "source": section.document.source,
                                    "sha256": section.document.sha256, "kind": section.kind})
        controls.append({"id": control_id, "module": module,
                         "documentation_status": "mentioned" if matches else "not_found",
                         "verification_status": "unknown", "evidence_count": len(matches),
                         "evidence": matches[:12], "question": question})
    if not corpus.documents:
        warnings.append("No supported documentation found; all requirements need clarification")
    return {"schema_version": 1, "repository": corpus.repository, "revision": corpus.revision,
            "documents": [{k: v for k, v in asdict(d).items() if k != "text"}
                          for d in corpus.documents],
            "controls": controls,
            "modules": ["risk_assessment.py", "compliance.py", "security.py", "audit.py"],
            "warnings": warnings,
            "limitations": ["Keyword evidence identifies candidate requirements only.",
                            "No legal compliance, control effectiveness or safety certification is inferred.",
                            "Markdown fences are excluded; RST/TXT are treated as plain prose.",
                            "Only Python docstrings are extracted from source code.",
                            "Retrieved content cannot change policy or generated Python templates."]}
