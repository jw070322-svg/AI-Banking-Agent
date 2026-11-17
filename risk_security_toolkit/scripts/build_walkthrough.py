"""Keep the shareable source walkthrough synchronized with the implementation."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    preface = '''# Implementation walkthrough

1. **Connect:** Use bounded read-only GitHub REST, an existing local clone, or an
   authorized connector export. Resolve remote references to one immutable commit.
2. **Parse:** Extract prose and Python docstrings without importing repository
   code. Keep file hashes, source links and matching line numbers.
3. **Plan risk assessment:** Use explicit policy thresholds and validated risk
   inputs; the included likelihood/impact scale is a configurable prototype.
4. **Plan compliance evidence:** Separate documentation mentions from verification.
   Missing verification remains unknown; human reviewers establish applicability.
5. **Plan security:** Check server-verified identity, allowlisted tools, scopes and
   resource ownership. Write operations remain under review pending confirmation,
   parameter validation, revalidation, idempotency and execution adapters.
6. **Plan audit:** Emit the requested eight summary fields with UTC timestamps.
   Minimize data before logging; common-token redaction is a secondary safeguard.
7. **Generate and validate:** Copy fixed templates into a new directory. Exercise
   parsing, error boundaries and generated imports with focused behavioral tests.

All source listings below are the actual implementation. Usage instructions,
scope limits and authoritative references are in README.md. The exported snapshot
contains the two primary repository documents and is intentionally omitted here.

## Code

'''
    paths = [ROOT / "pyproject.toml", *sorted((ROOT / "risk_scaffold").rglob("*.py")),
             ROOT / "examples" / "evaluate_controls.py", ROOT / "tests" / "test_workflow.py"]
    listings = []
    for path in paths:
        language = "toml" if path.suffix == ".toml" else "python"
        listings.append(f"### `{path.relative_to(ROOT).as_posix()}`\n\n```{language}\n"
                        + path.read_text(encoding="utf-8").rstrip() + "\n```\n\n")
    conclusion = '''## Results and next actions

The workflow emits an evidence plan, review questions, four annotated modules and
an audit event. It does not certify compliance or enable banking writes. Review
policy, jurisdiction, identity, confirmation and audit contracts before integration.
See validation.json for the measured test results and session_log.json for 日志.
'''
    (ROOT / "SOURCE_WALKTHROUGH.md").write_text(preface + "".join(listings) + conclusion,
                                               encoding="utf-8")


if __name__ == "__main__":
    main()
