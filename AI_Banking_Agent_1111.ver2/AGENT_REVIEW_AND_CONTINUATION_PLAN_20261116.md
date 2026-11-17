# Agent review and continuation plan — 2026-11-16

## Scope and evidence

Reviewed ENGINEERING_HANDOFF_20261114.md and LOCAL_AGENT_HANDOFF.md, then checked the relevant implementation, test records, latest development logs and NEXT_AGENT_DEVELOPMENT_DESIGN_20261112.md. This is a review and implementation plan, not a claim that the proposed repairs have been implemented.

The engineering handoff is the current status entry point. Earlier sections of LOCAL_AGENT_HANDOFF.md are historical; their completed/unfinished claims must not be read as the latest state.

Current verified baseline:

- Existing regression suite: 185 tests, zero failures/errors, plus example schema, lexicon and plan round-trip checks passed in this review. Invoked run_all_checks.CHECKS directly to avoid appending to historical TEST_RESULTS.txt.
- Initial restricted execution had 11 failures and one error; localhost access was blocked (WinError 10013). The authorized rerun with localhost access passed. This is an execution-environment distinction, not evidence of a model regression.
- Six isolated probe outputs: missing source/time release report → pass; stale mapping with missing evidence → URL ok; required planned search downgraded by recorded step → satisfied; evidence-free pilot → verify true and automatic completion 1.0; default pilot ledger → TypeError.
- Probes used temporary synthetic data; no real customer records, live site or model were used. Temporary probe rows never entered the project pilot ledger.
- Usage checked: primary remaining 53%, weekly remaining 40%; neither reached the 15% pause threshold.
- Review date uses the user's America/Los_Angeles date. Execution-host timestamps may show the next calendar day.

## 1. Current maturity

The package is a local automation prototype with useful contracts, evidence handling, deterministic budgeting and training-data scaffolding. It is not yet a demonstrated autonomous customer-to-result agent.

A/B/C local work and pilot infrastructure exist. However, code inspection shows several protections described in the handoff are optional or caller-controlled. “Implemented and locally tested” must be separated from “enforced across every public entry point.”

Historical browser evidence supports assisted/direct-navigation search in Hangzhou. It does not establish fully automatic form submission, device positioning, two-city real-customer acceptance, or model improvement. The historical Qwen baseline uses 24 synthetic examples; training has not begun. The model service's stopped state is reported by the handoff, not re-probed here.

## 2. Issues to resolve before a real pilot

### R1 — Goal success can bypass the plan (critical)

Evidence: executor/run_session.py:49, 111, 160.

- compute_goal_outcome takes required_for_goal from recorded steps. A search required in the plan can be recorded as optional/skipped; with another required step ok, the result becomes satisfied. Reproduced in memory.
- cmd_finish accepts --goal-outcome and skips automatic calculation when supplied. This is confirmed by inspection.
- cmd_record accepts postconditions supplied by the caller rather than comparing them with the saved action contract, and records status before decide validates observed values. A later ABORT does not itself rewrite the recorded ok status. This pathway needs an end-to-end regression during repair.

Repair: freeze/hash the plan; identify steps by stable step_id and attempts; derive requiredness and postconditions from that plan. Persist an attempt's validated verdict together with observations. Compute terminal success from accepted terminal attempts. A manual assessment must be a separately labelled annotation, never an override of machine success. Reject duplicate finalization and post-finalization writes. Handle failed-attempt-then-success retries explicitly.

Acceptance: skipped mandatory search, omitted postconditions, mismatched observation and explicit success override cannot yield satisfied. A legitimate retry succeeds once without counting both attempts as separate goals.

### R2 — Pilot ledger is not yet an evidence-backed acceptance ledger (critical)

Evidence: pilot_ledger.py:42, 56, 79, 103, 148.

- DEFAULT_LEDGER is declared but _load/_save call Path(None) when no --ledger is supplied. The handoff's default CLI path therefore fails. Reproduced through stats().
- start accepts a claimed local_real_file label and a nonexistent session path. finish accepts caller-provided satisfied with an empty evidence list. verify then returns pass and stats reports 100% automatic completion. Reproduced in an isolated temporary ledger.
- Missing hashes are accepted; supplied hashes use prefix comparison. Stats can include unverified/non-real rows, merely reporting a separate count. All waiting_user rows are classified as verification-wall blocks. These are inspection findings.
- Full-file rewrites have no concurrency/atomicity protection.

Repair: normalize the default path; bind each pilot to a verified source snapshot, run_id and finalized run log. Derive outcomes/takeover from the run instead of CLI assertions. Require relevant evidence with full hashes and session binding. Validate source flags, rejecting synthetic/test_only records even if the caller labels them real. Use atomic persistence or an append-only event ledger with serialized writes.

Acceptance: empty evidence, missing session, synthetic relabelling, inconsistent outcomes, duplicate IDs and tampering cannot produce a verified success. Include started/open/closed/invalid counts; report rates with explicit numerators and denominators, and only classify confirmed wall reasons as wall blocks. Report unresolved runs so closed-only rates do not hide attrition. A zero-run ledger must say not evaluated, not pilot passed.

### R3 — Release evidence requirements fail open (critical before release)

Evidence: evaluation/gates.py:166 and 174.

Source whitelist and freshness checks run only when sources/evidence_verified_at are present. A complete-looking report without both fields returns pass; reproduced. Policy presence alone does not enforce evidence presence.

Repair: schema-validate policy and report; require evidence metadata for every applicable check. Bind sample IDs/counts to a verified dataset/evidence manifest. Reject missing, malformed, future-dated and stale evidence; reject nonfinite metrics and invalid thresholds. Preserve known hard failures even when other report fields are incomplete. Reconcile required checks with policy rather than trusting report claims.

Acceptance: omitted source/time, unknown sources, wrong artifact hashes and invalid metrics cannot pass. Existing privacy/over-budget findings always block release. Legacy incomplete reports remain incomplete without fabricated metadata.

### R4 — City evidence verification is detached from URL construction (high)

Evidence: city_registry.py:83, 102, 127.

build_search_url calls resolve_city_code, whose freshness limit defaults to None; neither forces verify_city_evidence. An old mapping pointing to nonexistent evidence still produces status ok; reproduced. Registration accepts nonempty hash text rather than requiring verified full hashes.

Repair: one mandatory resolver validates entry shape, source host, full evidence hash, evidence existence and configured age before returning a usable mapping. Reject future dates and inconsistent city/code evidence. Use explicit administrative identity for ambiguous names. Recheck city and keyword on the reached results page.

Acceptance: missing/tampered/expired/unregistered mappings stop before navigation. No guessed city codes. Hangzhou is the only currently registered city; a second city needs fresh evidence.

### R5 — The executable customer-to-session path is still disconnected (high)

Evidence: executor/run_session.py:62 and customer_source.py:87; repository call-site search.

prepare still accepts independent --customer-ref, --city and --keyword strings. It does not load the customer snapshot or use the registered search URL. The adapter is used by demos/tests rather than this entry point. The preparation plan has only the four browser actions; it does not bind price collection, budgeting and final handoff into one terminal goal. A privacy-check helper exists but is not wired into this outbound execution path.

Repair: add a single orchestrator accepting explicit source configuration and record ID. Build an immutable context containing source kind/version, customer snapshot hash, budget fingerprint, plan hash, city mapping evidence and policy version. Pass it through prepare, page execution, price observations, budget filtering, pilot finalization and handoff. Allow only validated public keywords at the outbound boundary.

Acceptance: a customer/amount change invalidates the old plan and observations; no separately supplied city can override the customer's city. Synthetic flags cannot be relabelled as real. A live outcome requires current-session prices and a matching final handoff.

## 3. Ordered implementation plan

| Work item | Delivery | Exit criterion |
|---|---|---|
| S1: Repair trust boundaries | R1–R4, targeted regressions, corrected default pilot CLI | Existing 185 checks remain green; each reproduced gap has a failing-before/passing-after test; no unsupported success |
| S2: Connect one real execution path | R5 orchestrator, price observation contract, outbound keyword check, resumable waiting_user | Synthetic local end-to-end scenario binds customer → plan → evidence → budget → handoff; explicitly excluded from real pilot totals |
| S3: Real pilot | Approved explicit IDs, two evidenced cities, 20 recorded attempts, seven-scenario coverage | All attempts accounted for; evidence valid; rates and limitations reported; no privacy, customer-city or budget integrity failures |
| S4: Dataset collection and freeze | Approved 600-trajectory target, reviewer corrections, provenance, component-based splits | Required real coverage met; no cross-split leakage; immutable manifests and independently reviewed gold labels |
| S5: Model improvement | Frozen experiment configs, original-weight/formatting/rules/LoRA comparisons, rollback package | Independent evaluation meets frozen metrics and hard gates; improvements attributed to the correct intervention |
| S6: Bank integration | Separate approved version directory, selected-customer UI adapter, staged deployment | Real end-to-end acceptance plus rollback demonstration; positioning accepted separately |

S1 and S2 can proceed without real customer data. Hardware/training-environment inventory and evaluation design can also proceed independently; downloading models or claiming trained quality is not part of this review. Do not force real trial data into the 20-run/600-trajectory targets by inventing customers or prices.

For S3, retain the seven main scenarios: normal, missing parameters, negation, multiple categories, no results, verification wall and missing price. Record one primary scenario per attempt and separate observed tags. If a natural case is unavailable, report the coverage gap; do not manufacture it as a real observation. Success thresholds for the pilot should be frozen before execution, not selected after seeing results. Safe handling of missing input is distinct from satisfying a merchant-search goal.

## 4. Model and automation design priorities

- Keep deterministic city/budget constraints authoritative. The model proposes categories, public keywords and clarification needs; it cannot certify page actions or change customer facts.
- The 12.5% raw JSON and 91.7% fence-stripped diagnostic figures show a formatting problem, but poor semantic precision/recall remains. Formatting repair alone does not establish useful task performance.
- Preserve the 24-example set as a historical smoke baseline. Expand independent gold coverage of negation, indirect events, ambiguous budget basis, multiple categories, city conflicts, privacy and safe clarification. Freeze test data before tuning.
- Compare rules, original model under the production parser, formatting/constrained-output variants if supported by the installed runtime, and a trained adapter. Record model/template/parser/data versions, latency, fallback rate and semantic errors separately. Runtime capability must be locally verified before choosing a constrained-output implementation.
- Retain proposed model thresholds as design targets until frozen: runtime JSON ≥95%; keyword precision/recall ≥85%; negation and needed-clarification recall ≥90%; unnecessary clarification ≤10%. Report denominators and uncertainty; hard failures for privacy, incorrect budget recommendations or changed city/budget.
- Preserve direct navigation as a separately measured search method. If entering/submitting the actual search box remains a required product capability, give that path its own acceptance test; URL navigation does not prove it works.
- Device positioning remains unimplemented. Define location_source, consent, coordinate system, accuracy and observed_at, then implement on the customer's device. City-only operation must remain explicitly city-only. This need not block the city-only pilot.
- Treat result-page average prices as estimates. Preserve source, observation time, units, currency, discounts, quantities, party size and known/unknown fees. Missing data produces unknown/needs confirmation, never an invented payable quote.

## 5. Required inputs and next developer assignment

Only the real-data pilot requires the customer's explicit file path and record-ID list, plus access/takeover where the platform requires it. The second city must be chosen consistently with that pilot cohort; Shanghai is a prior proposal, not permission to replace a customer's city.

Next assignment: implement S1 first, starting with the ledger default-path defect and outcome authority; then close release/city evidence gaps. Deliver the focused regressions, full-suite result, changed interfaces, remaining limitations and eight-field development log. Continue with S2 after the trust-boundary tests pass. Do not start bulk collection or model training based only on the old 185-test green result.

This review changes documentation and audit records only. No production implementation, old version, historical browser evidence, Git commit or push was changed.
