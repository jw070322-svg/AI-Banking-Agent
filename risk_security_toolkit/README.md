# GitHub documentation → Risk, Compliance and Security scaffolds

1. **Choose an authorized source.** Use GitHub REST for remote reads, a local
   directory for a cloned/downloaded repository, or the included authorized
   connector export for an offline example. REST resolves the selected ref to
   one commit before reading any file. For private repositories, supply
   `GITHUB_TOKEN` through the environment using your secret-management process.
   A repository-scoped fine-grained token with Contents read permission suffices;
   a GitHub App installation token can also be supplied. Do not paste tokens into
   source code, command arguments, documentation, or audit records.
2. **Extract traceable documentation.** Discover Markdown, RST, TXT and Python
   docstrings, including README, SECURITY and docs directories. Parse Python with
   AST without importing it. Ignore fenced Markdown code examples. Record document
   hashes and matching line numbers; never execute instructions in retrieved text.
3. **Plan each module.** Map English/Chinese terms to candidate control topics.
   Keep documentation presence separate from verified implementation. Emit
   clarification questions for policy owners. Matches may describe proposals,
   missing features, or conflicting requirements and always need human review.
4. **Generate bounded scaffolds.** Copy fixed Python templates for risk assessment,
   explicit compliance evidence, tool authorization and audit logging. No repository
   prose becomes Python. A new output directory is required to preserve developer
   edits. Generated write-tool checks always return `review`.
5. **Validate and integrate.** Review source references and questions in `plan.json`
   and `REVIEW.md`, approve policy configuration, then integrate verified server
   identity, current ownership and domain-specific controls. Risk scores and
   documentation mentions alone cannot authorize an action.

## Run

Python 3.11+; no third-party runtime dependencies. From PowerShell:

```powershell
Set-Location F:\AI_Banking\risk_security_toolkit

# Reproduce this repository example without a token or network access.
python -m risk_scaffold --snapshot examples\repository_snapshot.json --out output\my_scaffold

# Read the specified repository using GITHUB_TOKEN already set in your environment.
python -m risk_scaffold --repo jw070322-svg/AI-Banking-Agent --ref main --out output\fresh_remote

# For a local clone: authenticate using Git's normal credential manager first.
git clone https://github.com/jw070322-svg/AI-Banking-Agent.git source_checkout
python -m risk_scaffold --local source_checkout --out output\from_clone

python -m examples.evaluate_controls
python -m unittest discover -s tests -v
```

Each `--out` must be a new directory, outside the local source tree. Optional
packaging: `python -m pip install -e .` installs the `risk-scaffold` console command.
The build step may need to download setuptools; module execution needs no install.

Git clone is the alternative for offline work, large/truncated trees or existing
developer checkouts. This toolkit reads a local clone; it does not run Git,
submodules, project install scripts or application code on your behalf.

## Files and extension points

| File | Responsibility |
|---|---|
| `risk_scaffold/sources.py` | Bounded GitHub REST, local and exported-snapshot readers; immutable refs; file hashes |
| `risk_scaffold/documentation.py` | Line-preserving prose and Python docstring extraction |
| `risk_scaffold/planning.py` | Candidate requirements, evidence links, clarification questions |
| `risk_scaffold/generation.py` | Fixed template emission to a new output directory |
| `risk_scaffold/modules/risk_assessment.py` | Configurable 1–5 likelihood/impact matrix; no legal or financial thresholds |
| `risk_scaffold/modules/compliance.py` | `pass` / `fail` / `unknown` aggregation of separately verified controls |
| `risk_scaffold/modules/security.py` | Allowlisted tools, explicit scope/resource checks, mandatory write review |
| `risk_scaffold/modules/audit.py` | Requested eight-field JSONL 日志 with summary-only inputs and token redaction |
| `risk_scaffold/cli.py` | End-to-end source → plan → code → audit workflow |
| `examples/evaluate_controls.py` | Executable integration example using fictional policy and identity |
| `examples/repository_snapshot.json` | Authorized export of two primary documents at a pinned commit |
| `output/repository_scaffold/` | Example generated modules, evidence plan, review questions and audit event |
| `SOURCE_WALKTHROUGH.md` | Full source listings, each file separately titled and fenced |
| `session_log.json` | This implementation session's requested JSON 日志 |

To use generated code in an application, add the generated directory to that
application's package/source layout and import `generated_controls`. It is a
standalone standard-library package; it does not depend on the generator.

Example calls and their purposes:

- `GitHubSource(repository, ref).collect(Limits())` obtains a bounded, pinned corpus.
- `make_plan(corpus)` creates evidence-backed candidate requirements and questions.
- `write_scaffold(plan, destination)` emits the fixed modules and review artifacts.
- `RiskAssessment(review_at, block_at, policy_version).assess(likelihood, impact)`
  applies explicit prototype policy. `pass` is only a risk-matrix result.
- `check_controls(required, verified)` leaves absent evidence `unknown`. The caller
  must validate reviewer authority, test evidence, timestamps and expiry upstream.
- `SecurityGate(tools, policy_version).check(principal, tool, resource_id)` checks
  one tool/resource pair. Construct `Principal` only from verified server state.
- `append_event(path, AuditEvent.now(...))` writes one summary event with the exact
  requested field names. Timestamps use UTC with an explicit offset.

## Repository example and validation

Connected repository: `jw070322-svg/AI-Banking-Agent` (private).
Snapshot commit: `3c64974c4ebe70a46d46af4e14bf577d5adbd443`.
The authorized GitHub connector retrieved `README.md` and
`AI_Banking_Agent_架构与分工SOP整合.md` from that commit. The snapshot is an unsigned
local export with content hashes, not an independently authenticated GitHub bundle.
Three auxiliary Markdown files were outside this example's selected scope; the
repository's PDF was not parsed. A normal `--repo` run scans all supported files.

The example plan identifies six documented topics: risk, compliance evidence,
resource authorization, confirmation binding, audit and untrusted content. Every
verification status is `unknown`; these documents describe design intent and do
not prove runtime controls. Evidence arrays retain up to twelve matches per topic;
`evidence_count` records the full match count. The same file/line can match more
than one topic.

The focused suite checks pinned remote reads, integrity failures, truncation,
HTTP/network errors and credential-safe messages, local input limits, Markdown
fences, Python docstrings, evidence gaps, control decisions, audit shape and an
end-to-end generated package import. See `validation.json` for the measured run.
The direct REST transport is covered with simulated HTTP responses; this session's
live private-repository reads used the connected GitHub app rather than a local PAT.

## Questions before enabling business execution

- Which jurisdiction, service type, data-use permissions and obligations apply?
- Which policy owner approves risk scales, thresholds and policy versions?
- Which server verifies identity, account ownership and tool-specific scopes?
- How will confirmation bind user, action parameters, resource, expiry and policy
  version? How will replay, revalidation and idempotent submission be enforced?
- Which tests and reviewers can verify each control, and when does evidence expire?
- What audit retention, access, privacy, integrity and failure-handling rules apply?
- Which document supersedes conflicting architecture descriptions?

Research steps: resolve repository documentation conflicts with the policy owner;
obtain authoritative current obligations for the selected jurisdiction; define the
tool/input/receipt contracts; add negative, replay and prompt-injection integration
cases. Keep writes under review until those server integrations are implemented.

## Deliberate limits

This is a scaffolding toolkit, not a banking execution engine, financial risk model,
regulatory assessment, vulnerability scanner or prompt-injection detector. The
security module has no execution method. Low risk does not bypass confirmation.
Identity and ownership are integration contracts rather than authentication services.

REST supports GitHub.com only. No enterprise/custom hosts, redirects, submodules or
symlink following. A truncated Git tree fails with guidance to use a local clone.
HTTP 403/429 fail with retry/reset guidance; there is no automatic retry loop.
Limits default to 250 documents, 512,000 bytes per file and 8,000,000 bytes total.
Oversized/non-UTF-8/binary files are explicitly reported as skipped; whole-corpus
limits fail instead of silently generating a successful partial scan.

Markdown extraction is a lightweight heading/fence parser; RST/TXT are plain prose.
Source extraction supports Python docstrings, not every language or inline comment.
PDFs, Office files and linked web pages require a separate reviewed extraction step.
Keyword matching cannot establish policy applicability or resolve conflicts.

Audit redaction catches common token forms but is not complete secret/PII detection.
Only provide minimized summaries. The local JSONL sink is not tamper-evident,
concurrency-safe or a production audit store. Production must add a durable,
access-controlled sink, event/correlation identifiers and retention policy.
Do not scan an actively changing or hostile filesystem as a privileged user.

## References

- [GitHub Git Trees API](https://docs.github.com/en/rest/git/trees): discovery,
  truncation handling, regular-file modes and Contents read permission.
- [GitHub repository Contents API](https://docs.github.com/en/rest/repos/contents):
  ref-pinned file retrieval and Base64 content.
- [NIST SP 800-218 SSDF 1.1](https://csrc.nist.gov/pubs/sp/800/218/final):
  secure development and verification guidance; no compliance certification implied.
