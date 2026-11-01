# 08 · Module 6 — Tool Calling Layer

> Status: **implemented prototype, mock-backed data, safety ports unconnected by default.**
>
> This module does **not** claim that the completed Risk Engine or Compliance
> Guard is connected. `execute_transaction()` fails closed unless both ports are
> ready. No real transaction gateway exists; every transaction path is simulated.

## 1. Scope and boundaries

Module 6 adds a self-contained tool-calling layer under
`bank_agent/tool_calling/`:

- one centralized Tool Registry for the requested 13 tools;
- typed input/output contracts and strict validation;
- standardized result envelopes, errors, provenance and evidence;
- deterministic financial calculations;
- sequential and conditional plan execution;
- tracing, optional JSONL execution logs, and Markdown report generation;
- explicit integration ports for the existing Risk Engine and Compliance Guard;
- tests covering contracts, tools, safety, orchestration, and an end-to-end report.

The following existing components are **untouched**:

- `bank_agent/risk/` — Risk Engine, policy engine, preview store, approval,
  Compliance Guard/scanner, action log and control matrix;
- `bank_agent/tools.py` — the legacy pipeline Tool Registry;
- `bank_agent/orchestrator.py` and `bank_agent/stages/` — the legacy pipeline.

Module 6 does not recreate risk policy, preview/approval rules, PII scanning, or
compliance controls. It defines ports for those completed modules and clearly
marks them unconnected until a real adapter is injected and verified.

### 1.1 Tool-list decision

The 13 requested tools are registered **without additions or removals**:

```text
get_account_balance, get_transactions, analyze_cashflow,
calculate_financial_health, calculate_risk, search_products,
compare_products, retrieve_policy, calculate_loan, calculate_portfolio,
create_budget, create_alert, execute_transaction
```

The existing pipeline uses a separate legacy registry and the names
`query_transactions`, `transfer_funds`, etc. Module 6 deliberately uses the
requested names and lives in a separate namespace. Both registries can coexist;
the legacy pipeline is not rewired or broken.

### 1.2 What is implemented vs simulated

| Status | Meaning in this module |
|---|---|
| `implemented` | Deterministic logic is complete; inputs are supplied by the caller or internal deterministic code. |
| `mocked` | Logic is implemented but the data store/catalogue/assumptions are in-memory or simulated. |
| `awaiting_integration` | The real downstream capability is not connected; the tool is fail-closed/simulation-only. |

“Mocked” does **not** mean the calculation is random. All calculators are
deterministic; “mocked” identifies the data source or persistence boundary.

---

## 2. Architecture

```text
Agent / planner (not part of this module)
        │  declares ToolPlan: steps, refs, conditions, per-step confirmations
        ▼
ToolOrchestrator ───────────────► TraceSink (memory / optional JSONL)
        │  sequential dispatch              │
        ▼                                   │
ToolRegistry                                 │
  1. discover / version / permission        │
  2. schema validation                      │
  3. confirmation + idempotency             │
  4. safety ports (if connected)            │
  5. handler                                 │
  6. output validation + evidence           │
        │                                    │
        ├── ComplianceGuardAdapter ──► existing Compliance Guard (not wired)
        ├── RiskEngineAdapter ───────► existing Risk Engine (not wired)
        ├── 13 tool handlers
        │      ├── MockBankService ──► existing deterministic MockBank
        │      ├── ProductCatalog / PolicyCorpus (explicit mocks)
        │      ├── PlanningStore (in-memory)
        │      └── TransactionGateway (unavailable by default; mock available)
        └── EvidenceBundle
                    │
                    ▼
        MarkdownReportGenerator (structured results only)
```

Separation of responsibilities:

| Component | Responsibility |
|---|---|
| `ToolRegistry` | Registration, discovery, authorization, validation, dispatch, safety gates, idempotency, evidence, errors. |
| `ToolOrchestrator` | Plan validation, prior-result references, conditions, dependencies, step ordering, partial/unknown status aggregation. It does not implement tools or bypass the registry. |
| `ToolPlan` / `ToolStep` | Declarative plan, no executable expressions or `eval`. |
| Adapters | Ports to the completed safety modules; injectable. |
| `MarkdownReportGenerator` | Renders only structured outputs and evidence; no invented facts. |

### 2.1 Source layout

```text
bank_agent/tool_calling/
├── __init__.py          # public exports
├── adapters.py          # Risk Engine / Compliance Guard ports
├── calculations.py      # deterministic financial math
├── errors.py            # stable error codes
├── mocks.py             # explicitly labelled TEST-ONLY safety doubles
├── models.py            # context, definition, result, evidence datatypes
├── orchestration.py     # plans, conditions, sequential execution
├── registry.py          # centralized registry + dispatch
├── reporting.py         # evidence-only Markdown report
├── schema.py            # stdlib JSON-Schema subset
├── services.py          # mock bank access, catalogue, policy store, planning store, gateways
├── tracing.py           # in-memory / JSONL traces
├── utils.py             # canonical JSON, hashing, decimal helpers
└── tools/
    ├── accounts.py      # get_account_balance, get_transactions
    ├── analysis.py      # analyze_cashflow, calculate_financial_health, calculate_risk
    ├── products.py      # search_products, compare_products
    ├── policies.py      # retrieve_policy
    ├── planning.py      # calculate_loan, calculate_portfolio, create_budget, create_alert
    └── transactions.py  # execute_transaction
```

---

## 3. Unified Tool Registry

### 3.1 Registration invariants

`ToolRegistry.register()` rejects definitions that violate any of these rules:

- snake-case unique name; semantic version `x.y.z`;
- non-empty description, category, permissions and data sources;
- object input schema with `additionalProperties=false`;
- object output schema;
- known risk tier (`R0`–`R4`);
- mutating tools must be `R3`/`R4` and must require confirmation;
- all state-changing calls must be replay-safe with an idempotency key;
- `R4` must require safety checks;
- mutating tools are never automatically retried (registry forces one attempt);
- `implementation_status` must be `implemented`, `mocked`, or
  `awaiting_integration`.

No dynamic imports, arbitrary callables from model output, shell execution, or
SQL construction exist in the registry.

### 3.2 Discovery

```python
from bank_agent.tool_calling import ToolRegistry

registry = ToolRegistry()
for descriptor in registry.discover(category="analysis", read_only=True):
    print(descriptor["name"], descriptor["version"],
          descriptor["implementation_status"], descriptor["input_schema"])
```

Each descriptor includes the version, permissions, risk tier, read-only flag,
confirmation/idempotency requirements, implementation status, data sources,
simulation flag, schemas and tags. Filtering happens in the registry; callers
do not need a second tool catalogue.

### 3.3 Dispatch

```python
from bank_agent.tool_calling import ToolCallContext

context = ToolCallContext(
    user_id="CUST-001",                 # set by authenticated session, not the LLM
    session_id="SESS-DEMO",
    permissions=frozenset({"account:read"}),
)
result = registry.execute("get_account_balance", {"account_ref": "工资卡"}, context)

print(result.ok, result.status, result.summary, result.evidence.evidence_id)
```

Expected failures are returned as `ToolCallResult`, not thrown:

```json
{
  "ok": false,
  "status": "error",
  "tool": "get_transactions",
  "version": "1.0.0",
  "call_id": "CALL-…",
  "data": {},
  "error": {
    "code": "INVALID_ARGUMENTS",
    "message": "工具参数未通过输入契约校验。",
    "retryable": false,
    "details": {"issues": [{"path": "$.days", "code": "below_minimum", "message": "value must be >= 1"}]}
  },
  "meta": {
    "trace_id": "TRACE-…",
    "mutating": false,
    "risk_tier": "R1",
    "implementation_status": "mocked",
    "simulated": true,
    "phase": "input_validation",
    "safety": {
      "required": false,
      "production_checks_active": false,
      "compliance": {"status": "not_connected", "adapter_kind": "unconfigured"},
      "risk": {"status": "not_required"}
    }
  }
}
```

Missing context is a programming error and raises `TypeError`; it is never
inferred from arguments. `customer_id` is not part of any tool input schema.

### 3.4 Standard envelope

Every call contains:

| Field | Purpose |
|---|---|
| `ok`, `status` | `success`, `error`, or `unknown` for an uncertain mutation. |
| `tool`, `version`, `call_id` | Contract identity and correlation. |
| `data` | Schema-validated tool-specific object, including a deterministic `summary`. |
| `error` | Stable code, safe message, retryability and structured details. |
| `meta` | Trace ID, timing, risk tier, permissions, implementation/simulation status, safety outcomes, idempotency phase. |
| `evidence` | Source-linked payload and SHA-256 hash for successful calls. |

Output data is validated before it can become evidence or report content. An
invalid output is never returned as success; a mutating tool with an invalid
post-execution result is marked `unknown`, not retried.

---

## 4. Validation and error handling

### 4.1 Input validation

The stdlib-only schema validator supports the subset needed by these contracts:

- object `properties`, `required`, `additionalProperties`;
- arrays with bounds, item schema and unique items;
- strings with length, regex, enum and formats `decimal`, `date`, `year-month`;
- integers/numbers with bounds;
- booleans, nullable fields and default filling.

Money, rates and weights are decimal **strings**. This avoids binary floating
point drift. Unknown fields are rejected; direct `None` values must be declared
nullable. Validation messages describe the schema and path, not the submitted
value, so invalid PII is not copied into error logs.

### 4.2 Error codes

| Code | Meaning | Auto-retry |
|---|---|---|
| `INVALID_ARGUMENTS` | Schema/parameter failure | No |
| `TOOL_NOT_FOUND` | Tool not registered | No |
| `TOOL_UNAVAILABLE` | Handler not implemented | No |
| `PERMISSION_DENIED` | Context lacks a declared permission | No |
| `AUTH_INSUFFICIENT` | Adapter requires verified step-up not present | No |
| `CONFIRMATION_REQUIRED` / `CONFIRMATION_INVALID` | Missing/invalid explicit confirmation | No |
| `IDEMPOTENCY_KEY_REQUIRED` | Mutation has no stable idempotency key | No |
| `IDEMPOTENCY_CONFLICT` | Same key used for different arguments | No |
| `SAFETY_CHECKS_UNAVAILABLE` | Required Risk/Compliance adapter not ready | No |
| `COMPLIANCE_DENIED` / `RISK_DENIED` | Connected safety adapter denied | No |
| `COMPLIANCE_GUARD_ERROR` / `RISK_ENGINE_ERROR` | Safety port failed/invalid result; fail closed | No |
| `TRANSACTION_GATEWAY_UNAVAILABLE` | No permitted simulated gateway | No |
| `TOOL_OUTPUT_INVALID` | Output failed its contract | No |
| `ACCOUNT_NOT_FOUND` / `BENEFICIARY_NOT_FOUND` | MockBank ownership/lookup failure | No |
| `PRODUCT_NOT_FOUND` / `PRODUCT_TYPE_MISMATCH` | Catalogue/comparison failure | No |
| `RATE_LIMITED` / `UPSTREAM_TIMEOUT` | Declared transient handler failure | Read-only only |
| `MUTATION_OUTCOME_UNKNOWN` | Unexpected failure after a mutation started | **Never** |
| `INTERNAL_ERROR` | Sanitized unexpected read-only failure | No |

### 4.3 Safe recovery rules

1. Only read-only tools may retry. Retry requires an error explicitly declared
   retryable and `max_attempts > 1`. No built-in read-only tool currently emits
   transient failures; the path is tested with a custom probe.
2. Mutations are never retried by the registry.
3. A mutating handler that throws an unexpected exception is reported as
   `status="unknown"` with `mutation_outcome_unknown=true`; callers must
   reconcile via receipt/audit rather than assume failure.
4. A post-handler output-contract failure on a mutation is also `unknown`.
5. Idempotency stores only successful results. Replays return the original
   payload with `meta.duplicate=true` and `phase="idempotent_replay"`.
6. Failures before the handler prove no side effect only up to the registry's
   phase boundary (`phase` is included in metadata).

The in-memory idempotency store is suitable for a single-process prototype; it
is not a distributed uniqueness guarantee.

---

## 5. Risk Engine and Compliance Guard integration

### 5.1 Existing modules and status

| Existing component | Path | Module 6 status |
|---|---|---|
| Risk & Compliance orchestration | `bank_agent/risk/engine.py` (`RiskComplianceEngine`) | **Not connected.** Adapter port only. |
| Deterministic policy | `bank_agent/risk/policy.py` (`PolicyEngine`) | Not connected; not duplicated. |
| Preview/approval | `bank_agent/risk/preview.py`, `auth.py` | Not connected; not duplicated. |
| Compliance scanning | `bank_agent/risk/compliance.py` (`ComplianceScanner`) | **Not connected.** Adapter port only. |
| Action Log | `bank_agent/risk/action_log.py` | Not used by Module 6; Module 6 has its own trace/evidence. |

Module 6 deliberately imports none of these modules. It does not define
competing risk rules or compliance checks. The mock transaction gateway reuses
the existing **MockBank transfer handler** only to make the simulated receipt
path realistic; it does not invoke or replace the Risk Engine/Compliance Guard.

### 5.2 Port interfaces

`bank_agent/tool_calling/adapters.py` defines:

`RiskEvaluationRequest`
: `request_id`, `trace_id`, `user_id`, `session_id`, `tool_name`,
  `tool_version`, `mutating`, `risk_tier`, `permissions`, `arguments`,
  `request_text`, `auth_level`, `confirmation_id`.

`RiskEvaluationResult`
: `allowed`, `decision_id`, `risk_level`, `requires_confirmation`,
  `requires_step_up`, `reasons`, `flags`, `policy_version`, `evaluated_at`,
  `metadata`.

`ComplianceEvaluationRequest`
: `request_id`, `trace_id`, `user_id`, `session_id`, `tool_name`,
  `tool_version`, `request_text`, `arguments`, `phase` (currently
  `"pre_execution"`).

`ComplianceEvaluationResult`
: `allowed`, `decision_id`, `findings`, `reasons`, `policy_version`,
  `evaluated_at`, `metadata`.

Both adapters must subclass the abstract ports. A production adapter reports:

```python
adapter_kind = "production"
is_connected = True
is_verified = True
```

The defaults are `UnconfiguredRiskEngineAdapter` and
`UnconfiguredComplianceGuardAdapter`: `is_connected=False`, `is_verified=False`,
`adapter_kind="unconfigured"`. Their `evaluate()` raises
`AdapterNotConnectedError`. `registry.safety_status()` reports the real state.

### 5.3 Lifecycle call points

For every call, in order:

1. resolve definition and version;
2. validate/normalize input schema;
3. check context permissions;
4. check explicit confirmation (state-changing tools);
5. check idempotency for state-changing tools;
6. **Compliance Guard** (`evaluate`, phase `pre_execution`):
   - every tool when a ready adapter is injected;
   - mandatory for `execute_transaction`;
7. **Risk Engine** (`evaluate`):
   - every state-changing tool when a ready adapter is injected;
   - mandatory for `execute_transaction`;
8. enforce adapter-returned confirmation/step-up requirements;
9. execute handler;
10. validate output and create evidence;
11. store idempotent result and emit sanitized trace.

If either required adapter is not ready, `execute_transaction` returns
`SAFETY_CHECKS_UNAVAILABLE` before the handler and before any balance change.

For read-only tools, the Risk Engine is not a meaningful authorization gate and
is recorded as `not_required`. A ready Compliance Guard may still block any tool.

### 5.4 Connecting the existing modules later

No registry rewrite is needed:

1. Implement `RiskEngineAdapter` as a bridge that preserves the existing
   engine's plan/preview/confirm/authorize/step-up lifecycle. A single
   `evaluate()` must not collapse R4 approval into a bare allow flag; the bridge
   is responsible for invoking the complete existing flow or refusing.
2. Implement `ComplianceGuardAdapter` around the existing
   `ComplianceScanner`/guard service, returning stable findings and a decision.
3. Inject both into `ToolRegistry(..., risk_engine=..., compliance_guard=...)`.
4. Set the production readiness fields only after integration tests prove them.
5. Add contract/negative tests and keep mocks disabled.

This is intentionally **not** delivered as a live adapter here. The Risk Engine
and Compliance Guard remain completed, untouched modules; the integration is a
future step, not a claim of this prototype.

### 5.5 Mock safety adapters

`bank_agent/tool_calling/mocks.py` contains `MockRiskEngineAdapter` and
`MockComplianceGuardAdapter`. They are:

- named and described as **TEST ONLY**;
- `adapter_kind="mock"`, `is_connected=True`, `is_verified=False`;
- never enabled unless the registry is constructed with
  `allow_mock_safety=True`;
- reported as `evaluated_mock` in metadata, never `verified`;
- required for exercising the transaction simulation harness in tests.

A mock can never be presented as the completed production module. The report
labels mock safety explicitly.

### 5.6 Transaction execution boundary

`execute_transaction()` is `R4`, `mutating`, confirmation-required,
idempotency-required, and safety-checks-required. It additionally:

- defaults to `UnavailableTransactionGateway`, which fails closed;
- accepts only a gateway with `simulated=True`; a gateway claiming to be live is
  rejected by the handler;
- returns `status="simulated_completed"` with `simulated=true`;
- never calls a real banking/payment API.

The test/demo `MockBankTransactionGateway` is explicitly labelled and reuses the
in-memory MockBank transfer handler. It only mutates MockBank balances. Its
receipt says it is not a real payment receipt. This is not a production
transaction path and does not by itself satisfy runtime R4 safety; the registry
still requires the Risk/Compliance ports.

---

## 6. Tool catalogue

### 6.1 Summary

| # | Tool | Access | Risk | Permission | Status | Data source |
|---|---|---|---|---|---|---|
| 1 | `get_account_balance` | read-only | R1 | `account:read` | mocked | existing MockBank |
| 2 | `get_transactions` | read-only | R1 | `transactions:read` | mocked | existing MockBank |
| 3 | `analyze_cashflow` | read-only | R2 | `transactions:read` | mocked | existing MockBank |
| 4 | `calculate_financial_health` | read-only | R2 | `analysis:read` | mocked | MockBank + deterministic formula |
| 5 | `calculate_risk` | read-only | R2 | `analysis:read` | mocked | fixed mock market assumptions |
| 6 | `search_products` | read-only | R2 | `products:read` | mocked | mock product catalogue |
| 7 | `compare_products` | read-only | R2 | `products:read` | mocked | mock product catalogue |
| 8 | `retrieve_policy` | read-only | R2 | `policy:read` | mocked | local mock policy corpus |
| 9 | `calculate_loan` | read-only | R2 | `analysis:read` | implemented | caller inputs + deterministic amortization |
| 10 | `calculate_portfolio` | read-only | R2 | `analysis:read` | mocked | caller inputs + fixed mock assumptions |
| 11 | `create_budget` | state-changing | R3 | `planning:write` | mocked | in-memory PlanningStore |
| 12 | `create_alert` | state-changing | R3 | `planning:write` | mocked | in-memory PlanningStore |
| 13 | `execute_transaction` | state-changing | R4 | `transfer:write` | awaiting integration | MockBank simulation gateway only |

All tool results include `summary`, `as_of`, metadata provenance, and an
evidence record with source names, collection time and payload SHA-256. The
authoritative machine-readable input/output schemas are returned by
`registry.describe(name)["input_schema"]` and `["output_schema"]`; the sections
below document their key fields and semantics.

**Runtime dependencies**

| Tool | Internal dependencies | External dependency status |
|---|---|---|
| `get_account_balance` | MockBank customer-scoped account access | None; real core-banking API not connected |
| `get_transactions` | MockBank transactions + account ownership | None; real transaction API not connected |
| `analyze_cashflow` | MockBank account/transaction service + deterministic aggregator | None; real data not connected |
| `calculate_financial_health` | MockBank balances/transactions/loans + deterministic score | None; not Risk Engine |
| `calculate_risk` | Fixed market assumptions + deterministic VaR | None; market-data feed not connected |
| `search_products` | Mock product catalogue | None; real catalogue not connected |
| `compare_products` | Mock product catalogue | None; real catalogue not connected |
| `retrieve_policy` | Local mock policy corpus | None; production RAG not connected |
| `calculate_loan` | Caller inputs + deterministic amortization | None |
| `calculate_portfolio` | Caller inputs + fixed mock assumptions | None; market-data feed not connected |
| `create_budget` | In-memory PlanningStore; registry confirmation/idempotency | None; no bank budgeting service |
| `create_alert` | PlanningStore; MockBank ownership when account supplied | None; no SMS/push service |
| `execute_transaction` | MockBank transfer mock, simulated gateway, Risk Engine port, Compliance Guard port, confirmation/idempotency | **Required adapters not connected by default; no real gateway exists** |

### 6.2 `get_account_balance`

- **Purpose:** return account balances/available credit for accounts owned by
  the authenticated customer.
- **Inputs:** optional `account_ref` string (1–32 chars; alias, last four or
  opaque ID). No complete card number is accepted.
- **Outputs:** `accounts[]` with account ID/type/last4/kind/currency/status and
  either debit balance/available or credit limit/outstanding/available credit;
  `count`, `as_of`.
- **Permissions/risk:** read-only, R1, `account:read`.
- **Data/provenance:** existing deterministic MockBank, mock flag; `as_of`.
- **Failures:** `INVALID_ARGUMENTS`, `ACCOUNT_NOT_FOUND` (including another
  customer's account), `PERMISSION_DENIED`, `TOOL_OUTPUT_INVALID`.
- **Recovery:** controlled error; no mutation and no retry.
- **Status:** mocked.

### 6.3 `get_transactions`

- **Purpose:** list date-scoped account transactions, totals and debit
  categories.
- **Inputs:** required `account_ref`; optional `days` (1–365, default 90),
  exact `category`, `limit` (1–200, default 50).
- **Outputs:** account identity, period, totals (counts, debit/credit/net),
  category totals, up to `limit` transactions, `truncated`, `as_of`.
  Aggregates cover the entire query period, not just returned rows.
- **Permissions/risk:** read-only, R1, `transactions:read`.
- **Data:** MockBank transactions; mock.
- **Failures:** `INVALID_ARGUMENTS`, `ACCOUNT_NOT_FOUND`, permission/output
  errors.
- **Recovery:** controlled error; no mutation.
- **Status:** mocked.

### 6.4 `analyze_cashflow`

- **Purpose:** deterministic income/expense/cash-flow/savings analysis over one
  account or all customer accounts.
- **Inputs:** optional `account_ref`; `days` 1–365 default 90;
  `include_transfers` default false.
- **Outputs:** scope, period, income/expenses/net/savings rate, 30-day
  normalized monthly averages, category shares, monthly trend, assumptions.
- **Rules:** internal transfers (`category="转账"`) are excluded by default to
  avoid double-counting both legs; averaging uses 30 days/month linear
  normalization.
- **Permissions/risk:** read-only, R2, `transactions:read`.
- **Data:** MockBank, mock.
- **Failures:** `INVALID_ARGUMENTS`, `ACCOUNT_NOT_FOUND`, output errors.
- **Recovery:** controlled error; no retry.
- **Status:** mocked.

### 6.5 `calculate_financial_health`

- **Purpose:** transparent 0–100 financial-wellbeing indicator, not a credit
  score and not the completed Risk Engine.
- **Inputs:** optional `account_ref`; `days` 30–365 default 90; optional
  `monthly_debt_payment` decimal string (otherwise sum the mock loan payments).
- **Outputs:** score, A–E grade, four weighted components (emergency reserve 30,
  savings capacity 25, debt burden 25, credit utilization 20), metrics,
  assumptions, limitations.
- **Rules:** liquid balance from debit accounts only; emergency months =
  liquid balance / normalized monthly expenses; DTI = monthly debt payment /
  normalized monthly income; utilization = outstanding / credit limit.
- **Permissions/risk:** read-only, R2, `analysis:read`.
- **Data:** MockBank + deterministic Module 6 scoring v1; mock data.
- **Failures:** invalid arguments, account not found, output contract errors.
- **Recovery:** controlled error; no retry.
- **Status:** mocked.
- **Boundary:** no risk-tier decision, no approval, no operational risk policy.

### 6.6 `calculate_risk`

- **Purpose:** advisory **market-risk** metrics for a supplied allocation:
  weighted expected return, volatility proxy, concentration HHI and parametric
  VaR.
- **Inputs:** required `portfolio_value` decimal string; required
  `allocations[]` of `{asset_class, weight}` (weights sum to 1, no duplicate
  classes); optional `horizon_days` 1–365 default 30; `confidence` one of
  `"0.90"`, `"0.95"`, `"0.99"`.
- **Asset assumptions:** fixed mock annual return/volatility for cash, bonds,
  domestic equity, global equity, gold and crypto. Weighted-average volatility
  is a conservative proxy without a correlation matrix.
- **Outputs:** VaR percentage/amount, expected horizon return, volatility proxy,
  HHI, largest weight, advisory risk level, flags, assumptions and model notes.
- **Permissions/risk:** read-only, R2, `analysis:read`.
- **Data:** fixed mock capital-market assumptions v1; simulated.
- **Failures:** invalid weights/sum/class/duplicates, schema errors, output
  errors.
- **Recovery:** controlled error; no retry.
- **Boundary:** **This is not the operational Risk Engine.** It does not grade
  transactions, grant approval, inspect account ownership, or replace the
  completed module. `risk_domain="market_risk_advisory"` is explicit.
- **Status:** mocked.

### 6.7 `search_products`

- **Purpose:** deterministic keyword/type search over the labelled mock product
  catalogue.
- **Inputs:** optional `product_type` (`savings`, `time_deposit`, `loan`,
  `credit_card`, `fund`), optional `query` ≤100 chars, `max_results` 1–20
  default 5.
- **Outputs:** matching product records (rate/fee/minimum/term/risk/liquidity/
  features/eligibility/tags/source date), count, filters, disclaimer, `as_of`.
  No match is a successful empty result, not an invented product.
- **Permissions/risk:** read-only, R2, `products:read`.
- **Data:** `MockBank simulated product catalogue v1`; mock.
- **Failures:** schema/permission/output errors only; no result is not an error.
- **Recovery:** no mutation; safe to retry at the caller's discretion.
- **Status:** mocked.

### 6.8 `compare_products`

- **Purpose:** side-by-side comparison of two to four products of the **same**
  type.
- **Inputs:** `product_ids[]` 2–4 unique IDs. Mixed product types are rejected
  because rate/fee semantics differ.
- **Outputs:** product records, attribute matrix, factual observations
  (highest/lowest indicative rate, lowest fee), disclaimer, `as_of`.
- **Permissions/risk:** read-only, R2, `products:read`.
- **Data:** mock catalogue.
- **Failures:** `INVALID_ARGUMENTS`, `PRODUCT_NOT_FOUND`,
  `PRODUCT_TYPE_MISMATCH`, output errors.
- **Recovery:** controlled error; no retry.
- **Status:** mocked.
- **Boundary:** observations are not recommendations or suitability decisions.

### 6.9 `retrieve_policy`

- **Purpose:** deterministic citation retrieval from a local mock policy corpus.
- **Inputs:** required `query` 1–200 chars; optional `category` (deposits,
  loans, cards, transfers, fees, privacy, investments); `top_k` 1–5 default 3.
- **Outputs:** matches with policy ID, title, category, version, effective
  dates, source, section, excerpt, score, citation, `stale`; `no_basis`;
  `content_trust="untrusted_reference"`; retrieval mode; disclaimer; `as_of`.
- **Rules:** Chinese bigram-assisted keyword retrieval; current versions rank
  before expired versions; no basis is explicit and never fabricated.
- **Permissions/risk:** read-only, R2, `policy:read`.
- **Data:** local mock policy corpus; not production RAG.
- **Failures:** schema/permission/output errors. No match is a successful
  `no_basis=true` result.
- **Recovery:** no mutation.
- **Security:** retrieval text is data only and can never trigger tool calls,
  change arguments, or grant permissions.
- **Status:** mocked.

### 6.10 `calculate_loan`

- **Purpose:** deterministic amortization for equal-installment (等额本息) or
  equal-principal (等额本金) loans.
- **Inputs:** required `principal` money string, `annual_rate_percent` decimal
  string 0–100, `term_months` 1–480; optional `repayment_method` default
  `equal_installment`.
- **Outputs:** monthly/first/last payment, total payment/interest, 12-period
  schedule preview, truncation flag, rounding rule, assumptions, disclaimer.
- **Rules:** interest compounds monthly at annual rate / 12; each period is
  rounded to cents half-up; the final period adjusts remaining principal.
- **Permissions/risk:** read-only, R2, `analysis:read`.
- **Data:** caller inputs + deterministic amortization v1; implemented (not a
  bank quote).
- **Failures:** principal ≤0, rate outside 0–100, schema errors, output errors.
- **Recovery:** no mutation.
- **Status:** implemented.
- **Boundary:** illustrative only; not a credit decision or binding offer.

### 6.11 `calculate_portfolio`

- **Purpose:** deterministic scenario growth for a user-supplied allocation.
- **Inputs:** required `initial_amount` ≥0, `allocations[]` (classes/weights sum
  to 1, no duplicates); optional `monthly_contribution` default 0, `horizon_years`
  1–40 default 10. Initial and monthly contribution cannot both be zero.
- **Outputs:** weighted expected return/volatility proxy, total contributions,
  projected/stress values, projected gain, annual timeline, assumptions,
  model notes, disclaimer.
- **Rules:** fixed mock assumptions; nominal annual return/12 monthly
  compounding; end-of-month contributions; stress return is expected return
  minus 1.645 × volatility, floored at −95%; no randomness.
- **Permissions/risk:** read-only, R2, `analysis:read`.
- **Data:** caller inputs + fixed mock assumptions v1; simulated.
- **Failures:** invalid allocation/sum/duplicates, negative contributions,
  zero-everything, schema/output errors.
- **Recovery:** no mutation.
- **Status:** mocked.
- **Boundary:** no real market data, no investment execution, not advice.

### 6.12 `create_budget`

- **Purpose:** create a local monthly budget record.
- **Inputs:** required `monthly_income` >0 and 1–20 categories
  `{category, limit >0}`; optional `name` ≤60, `month` `YYYY-MM` (default current
  month). Duplicate/empty categories are rejected.
- **Outputs:** budget ID, name, month, income, total budgeted, unallocated
  (may be negative), category shares, status, created time,
  `persistence_mode="in_memory_mock"`, notes, `as_of`.
- **Permissions/risk:** state-changing, R3, `planning:write`.
- **Safety:** **explicit confirmation and idempotency key required**. The key
  comes from trusted `ToolCallContext`, never from model arguments. The
  orchestrator derives `<plan_id>:<step_id>`; callers must supply a stable key.
- **Data:** caller inputs + in-memory PlanningStore; no real bank budget,
  deduction, or automatic transfer.
- **Failures:** confirmation/idempotency errors, invalid amounts/categories,
  permission/output errors, `IDEMPOTENCY_CONFLICT`.
- **Recovery:** repeats with the same key return the stored result; no retry for
  mutations; restart loses the record.
- **Status:** mocked.

### 6.13 `create_alert`

- **Purpose:** create a local balance/transaction/budget reminder rule.
- **Inputs:** required `alert_type` (`balance_below`, `transaction_above`,
  `budget_threshold`) and `threshold` >0; optional `account_ref` (mandatory for
  `balance_below`), `channel` (`in_app`/`sms`, default in_app), `note` ≤140.
- **Outputs:** alert ID, type, threshold, optional account, channel, status,
  delivery `{mode:"mock_not_sent", sent:false}`, created time,
  `persistence_mode="in_memory_mock"`, notes.
- **Permissions/risk:** state-changing, R3, `planning:write`.
- **Safety:** explicit confirmation and idempotency key required.
- **Data:** caller inputs + in-memory PlanningStore. No SMS/push is sent even if
  `channel="sms"`. There is no background monitoring/trigger engine in this
  prototype, so stored rules are never evaluated automatically.
- **Failures:** confirmation/idempotency errors, invalid threshold, missing
  account for balance alert, `ACCOUNT_NOT_FOUND`, output errors.
- **Recovery:** same as budget; no real delivery.
- **Status:** mocked.

### 6.14 `execute_transaction`

- **Purpose:** high-sensitivity **simulated** transfer. Not a production payment
  capability.
- **Inputs:** required `from_account_ref`, `beneficiary_name`, `amount` >0;
  optional `currency` default `CNY` (only CNY), `note` ≤140. Identity comes from
  trusted context, not arguments. Confirmation and idempotency keys are context
  fields, not input schema fields.
- **Outputs:** simulated transaction ID, `status="simulated_completed"`,
  `simulated=true`, duplicate flag, account/beneficiary summaries, amount, fee,
  before/after balance, executed time, disclaimer.
- **Permissions/risk:** state-changing, R4, `transfer:write`, confirmation,
  idempotency, safety checks.
- **Preconditions:** ready Risk Engine and Compliance Guard adapters; explicit
  confirmation; stable idempotency; permitted simulated gateway.
- **Failures:** `SAFETY_CHECKS_UNAVAILABLE`, `CONFIRMATION_*`,
  `IDEMPOTENCY_*`, `AUTH_INSUFFICIENT`, `COMPLIANCE_DENIED`, `RISK_DENIED`,
  `TRANSACTION_GATEWAY_UNAVAILABLE`, business transfer failures from MockBank,
  `MUTATION_OUTCOME_UNKNOWN`/`unknown`.
- **Recovery:** no automatic retry. Reusing the idempotency key returns the
  original simulated result. An unknown mutation outcome requires receipt/audit
  reconciliation; never assume success or failure.
- **Data:** MockBank simulation only.
- **Status:** `awaiting_integration`; no real gateway, no real funds.

---

## 7. Orchestration

### 7.1 Plan model

```python
from bank_agent.tool_calling import (
    ToolPlan, ToolStep, StepCondition, ToolCallContext, ToolOrchestrator,
)

plan = ToolPlan(
    goal="Check balances, compute cash flow, conditionally search products",
    context=ToolCallContext(
        user_id="CUST-001",
        session_id="SESS-DEMO",
        permissions=frozenset({
            "account:read", "transactions:read",
            "analysis:read", "products:read",
        }),
        request_text="帮我看看现金流和稳健产品",
    ),
    steps=(
        ToolStep("balance", "get_account_balance"),
        ToolStep(
            "cash", "analyze_cashflow",
            {"account_ref": "${balance.accounts.0.account_id}"},
            depends_on=("balance",),
        ),
        ToolStep(
            "products", "search_products",
            {"query": "稳健", "max_results": 3},
            condition=StepCondition("balance", "count", "gte", 1),
        ),
    ),
)

result = ToolOrchestrator(registry).run(plan)
print(result.status, result.summary)
```

### 7.2 References and conditions

- Argument references use `${step_id.path.to.field}` and must occupy the whole
  string. Type is preserved (do not concatenate strings).
- References must target an earlier step and are resolved from that step's
  validated `data`.
- Supported path segments are object keys and numeric list indexes.
- Conditions use a fixed operator set: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`,
  `contains`, `in`, `exists`, `truthy`.
- Numeric comparison is decimal-safe; booleans do not compare as integers.
- No Python expressions, `eval`, shell, or arbitrary callables are accepted.
- Forward references, duplicate step IDs, unknown tools, unknown dependencies
  and malformed conditions fail plan validation before any tool executes.

### 7.3 Ordering and failure policy

- Steps execute strictly sequentially.
- A step with a false condition is `skipped`; that is not a failure.
- A step whose prior-result reference or explicit dependency did not succeed is
  skipped (optional) or blocked (required, error).
- Required tool failure stops the plan; remaining steps are `not_run`.
- Optional tool failure allows later independent steps to continue; the plan is
  `partially_completed`.
- `partially_completed` / `failed` / `unknown` are distinct statuses.
- Mutations need per-step confirmation IDs in `ToolPlan.confirmations`; a
  single confirmation cannot be reused across steps. The orchestrator derives a
  stable per-step idempotency key automatically.
- An `unknown` mutation outcome stops the plan immediately and is surfaced as
  `status="unknown"`; no further calls are attempted.

---

## 8. Evidence, tracing and reports

### 8.1 Evidence

Each successful call produces `EvidenceItem`:

- evidence ID, call ID, trace ID, tool/version;
- declared data sources;
- deterministic summary;
- deep-copied payload and SHA-256 payload hash;
- implementation status and simulated flag;
- caveats/assumptions (bounded);
- collection timestamp.

`OrchestrationResult.evidence` aggregates all successful items and supports
serialization with the plan result. Failed/skipped calls produce no evidence.

### 8.2 Tracing/logging

`ToolRegistry` emits sanitized events through a `TraceSink`:

- `tool_call_started`, `tool_call_completed`, `tool_call_replayed`;
- `tool_call_rejected`, `tool_call_failed`, `tool_call_unknown`, `tool_call_retry`;
- plan events from the orchestrator: `plan_started`, `plan_step_skipped`,
  `plan_step_started`, `plan_step_finished`, `plan_finished`.

Events include IDs, tool/version, phase, outcome code, timing and hashes of
arguments/results. They do **not** include raw arguments, response payloads or
request text. `JsonlTraceSink(path)` provides an append-only local trace;
production should use the existing immutable audit/action-log infrastructure.

### 8.3 Report generation

`MarkdownReportGenerator` renders:

- plan/trace identity and execution status;
- step status table and evidence-only findings;
- tool-specific tables for balances, cash flow, health, products, policies,
  loans, projections, budgets, alerts and simulated receipts;
- failures/skips, assumptions/limitations, safety/integration status, evidence
  index and structured errors.

The report never creates a financial number or safety conclusion that is not in
the tool result. It explicitly says when Risk Engine/Compliance Guard did not
run, and labels mock safety and simulated transactions.

```python
from bank_agent.tool_calling import MarkdownReportGenerator

report = MarkdownReportGenerator().render(result)
MarkdownReportGenerator().write(result, "reports/financial-review.md")
```

---

## 9. Tests and runnable demo

Run all repository tests:

```bash
python3 -m unittest discover -s tests -v
```

Current result: **101 passed** = 42 existing + 59 Module 6 tests.

Run the read-only demo and write an evidence report:

```bash
python3 scripts/demo_tool_calling.py
```

Add a simulated transaction (TEST ONLY mock safety adapters + simulated
gateway; no real funds move):

```bash
python3 scripts/demo_tool_calling.py --mock-transaction
```

Reports are written under `reports/` (ignored by git) and explicitly label
simulations and safety integration status.

New Module 6 tests:

| File | Tests | Coverage |
|---|---:|---|
| `tests/test_tool_calling_registry.py` | 18 | exact 13-tool list, discovery, strict schema validation, permission failures, output contract, sanitized errors, unknown mutation outcome, confirmation/idempotency, replay/conflict, retry-only-read-only, trace/PII, JSONL, registration invariants, disconnected safety. |
| `tests/test_tool_calling_tools.py` | 14 | balance/transaction ownership and recalculation, cash flow, health, market risk, product search/compare, policy citations/staleness/no-basis, loan amortization, portfolio projection, budget, alert, evidence. |
| `tests/test_tool_calling_safety.py` | 13 | default fail-closed transaction, mock opt-in, compliance/risk denials, confirmation/idempotency ordering, unavailable gateway, simulated success, replay/conflict, step-up, non-simulated gateway rejection, placeholder honesty. |
| `tests/test_tool_calling_orchestration.py` | 14 | sequential refs, conditions, validation, missing fields, fail-fast, optional failure, blocked required dependencies, per-step confirmation, full end-to-end report, mock safety report, failed-plan report. |

Notable negative assertions:

- no account from another customer is returned;
- no transaction runs without ready safety adapters;
- mock adapters never become active without explicit opt-in;
- no raw arguments/PII appear in traces;
- no report claims production risk/compliance checks ran;
- no plan continues after an unknown mutation outcome.

---

## 10. Usage quick reference

### Discover

```python
from bank_agent.tool_calling import ToolRegistry
registry = ToolRegistry()
print(registry.names())
print(registry.discover(category="products"))
```

### Call a read-only tool

```python
from bank_agent.tool_calling import ToolCallContext
ctx = ToolCallContext(
    user_id="CUST-001", session_id="SESS-1",
    permissions=frozenset({"transactions:read"}),
)
print(registry.execute("analyze_cashflow", {"days": 90}, ctx).to_dict())
```

### Configure safety ports (future)

```python
registry = ToolRegistry(
    services=ToolServices.demo(),
    risk_engine=ExistingRiskEngineAdapter(...),      # not included
    compliance_guard=ExistingComplianceAdapter(...), # not included
)
```

For tests only:

```python
from bank_agent.tool_calling import MockRiskEngineAdapter, MockComplianceGuardAdapter
registry = ToolRegistry(
    services=ToolServices.demo().with_mock_transaction_gateway(),
    risk_engine=MockRiskEngineAdapter(),
    compliance_guard=MockComplianceGuardAdapter(),
    allow_mock_safety=True,
)
```

This test configuration still produces only a simulated transaction and labels
the safety checks as mock.

### Trace to JSONL

```python
from bank_agent.tool_calling import JsonlTraceSink, ToolRegistry
registry = ToolRegistry(trace_sink=JsonlTraceSink("logs/tool-calls.jsonl"))
```

---

## 11. Known limitations and remaining integration work

- **Risk Engine and Compliance Guard are not connected.** No production safety
  claim is possible. `execute_transaction()` fails closed by default.
- **No real banking/payment API.** Account data is MockBank; products/policies
  are explicit mocks; budgets/alerts are in-memory and non-durable.
- **No real RAG.** Policy retrieval is deterministic keyword matching over a
  local corpus, not the team's RAG/knowledge service.
- **No production auth/approval UI.** Confirmation and step-up are trusted
  orchestration context, not an OTP/biometric proof. The existing approval
  module must supply these in production.
- **No distributed idempotency.** The store is process-local; production needs
  a database unique constraint/transaction.
- **No enforced timeouts/circuit breakers.** `max_attempts` supports read-only
  retry, but no tool timeout is enforced.
- **No multi-version simultaneous serving.** One version per tool name; version
  metadata is returned, but version negotiation/rollback is future work.
- **No prompt-injection/PII scanning is active by default.** The completed
  Compliance Guard is not wired, so only the deterministic plan restrictions
  (no eval, allowlisted operators, trusted context) are active. Retrieval text
  is marked untrusted. A ready guard screens pre-execution context; production
  should also scan/model-gate tool output and redact report goals before they
  reach users.
- **No concurrency guarantee for same-key mutations.** There is an in-process
  lock, but two racing calls can both reach a handler before one stores the
  idempotency record. Production must enforce uniqueness at the downstream
  transaction boundary.
- **`calculate_risk` is market-risk advisory only.** It is not the bank's
  operational Risk Engine and does not authorize transactions.
- **No real fund movement is possible** through this module.

---

## 12. Integration checklist (future)

- [ ] Implement a `RiskEngineAdapter` preserving existing
      preview/confirm/authorize/step-up behavior.
- [ ] Implement a `ComplianceGuardAdapter` around the completed guard.
- [ ] Verify adapter `is_connected/is_verified` only after integration tests.
- [ ] Inject both and disable `allow_mock_safety` in all non-test environments.
- [ ] Replace the in-memory idempotency store with a durable unique-key store.
- [ ] Add tool timeout/circuit-breaker policy and OpenTelemetry integration.
- [ ] Connect a production RAG service with source/version/expiry checks.
- [ ] Replace `MockBank`, product catalogue, policy corpus and PlanningStore with
      approved banking services.
- [ ] Add Action Log integration if Module 6 is promoted beyond prototype.
- [ ] Re-run contract, negative, concurrency and end-to-end tests.
