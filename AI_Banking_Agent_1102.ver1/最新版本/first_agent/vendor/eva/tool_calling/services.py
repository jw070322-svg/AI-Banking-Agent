"""Data and side-effect services used by Module 6.

Everything here is a mock or an in-memory reference implementation:
- account/transaction/loan data comes from the existing deterministic MockBank;
- product and policy data are explicitly labelled mock catalogues;
- budgets/alerts live in process memory and disappear on restart;
- the real transaction gateway is not implemented. A separately named mock
  gateway can be injected only by tests/demos.
"""

from __future__ import annotations

import re
import threading
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

from ..data import TODAY, MockBank
from ..models import new_id, utc_now
from ..tools import ToolRegistry as ExistingToolRegistry
from .errors import (
    BENEFICIARY_NOT_FOUND,
    TRANSACTION_GATEWAY_UNAVAILABLE,
    ToolLayerError,
)
from .utils import money_text, query_terms


class MockBankService:
    """Customer-scoped access to the existing in-memory bank."""

    def __init__(self, bank: MockBank) -> None:
        self.bank = bank

    def owned_accounts(self, user_id: str) -> list[dict[str, Any]]:
        return [
            account
            for account in self.bank.accounts.values()
            if account["customer_id"] == user_id
        ]

    def resolve_accounts(
        self, user_id: str, account_ref: str | None = None
    ) -> list[dict[str, Any]]:
        if account_ref:
            return [self.bank.find_account(user_id, account_ref)]
        owned = self.owned_accounts(user_id)
        if not owned:
            raise ToolLayerError(
                "ACCOUNT_NOT_FOUND",
                "未找到当前客户名下的账户。",
            )
        return owned

    def transactions(
        self,
        accounts: Iterable[dict[str, Any]],
        *,
        days: int,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        account_ids = {account["account_id"] for account in accounts}
        from_date = TODAY - timedelta(days=int(days))
        rows = [
            tx
            for tx in self.bank.transactions
            if tx["account_id"] in account_ids
            and from_date <= date.fromisoformat(tx["date"]) <= TODAY
            and (not category or tx["category"] == category)
        ]
        rows.sort(key=lambda item: (item["date"], item["tx_id"]), reverse=True)
        return rows

    def loans(self, user_id: str) -> list[dict[str, Any]]:
        return list(self.bank.loans.get(user_id, []))

    def liquid_balance(self, accounts: Iterable[dict[str, Any]]) -> Decimal:
        return sum(
            (
                account["balance"]
                for account in accounts
                if account["kind"] == "debit"
            ),
            Decimal("0.00"),
        )

    def credit_totals(
        self, accounts: Iterable[dict[str, Any]]
    ) -> tuple[Decimal, Decimal]:
        limit = Decimal("0.00")
        outstanding = Decimal("0.00")
        for account in accounts:
            if account["kind"] == "credit":
                limit += account["credit_limit"]
                outstanding += account["outstanding"]
        return limit, outstanding

    def ensure_beneficiary(self, user_id: str, name: str) -> None:
        try:
            self.bank.find_beneficiary(user_id, name)
        except Exception as exc:
            # Preserve ownership and whitelist checks inside the existing bank
            # mock; do not invent a competing beneficiary policy here.
            code = getattr(exc, "code", BENEFICIARY_NOT_FOUND)
            message = getattr(exc, "message", "未找到收款人。")
            raise ToolLayerError(code, message) from exc


class ProductCatalog:
    """Deterministic, explicitly simulated product catalogue."""

    PRODUCTS: tuple[dict[str, Any], ...] = (
        {
            "product_id": "PROD-SAVE-001",
            "name": "活期+（模拟）",
            "product_type": "savings",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "0.30",
            "rate_basis": "年化利率，随市场调整",
            "annual_fee": "0.00",
            "minimum_amount": "0.01",
            "term_months": None,
            "risk_level": "R1",
            "liquidity": "high",
            "features": ["随存随取", "无固定期限", "低风险"],
            "eligibility": "完成实名认证的个人客户",
            "tags": ["活期", "流动性", "稳健", "低风险"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-SAVE-002",
            "name": "七天通知存款（模拟）",
            "product_type": "savings",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "1.55",
            "rate_basis": "年化利率，提前 7 天通知支取",
            "annual_fee": "0.00",
            "minimum_amount": "50000.00",
            "term_months": None,
            "risk_level": "R1",
            "liquidity": "medium",
            "features": ["提前通知支取", "高于活期利率", "低风险"],
            "eligibility": "起存金额 50,000 元",
            "tags": ["通知存款", "稳健", "低风险", "短期"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-TERM-001",
            "name": "稳享三个月定期（模拟）",
            "product_type": "time_deposit",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "1.85",
            "rate_basis": "年化利率，到期一次性还本付息",
            "annual_fee": "0.00",
            "minimum_amount": "1000.00",
            "term_months": 3,
            "risk_level": "R1",
            "liquidity": "medium",
            "features": ["3 个月", "到期还本付息", "低风险"],
            "eligibility": "个人客户，起存 1,000 元",
            "tags": ["定期", "三个月", "稳健", "低风险"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-TERM-002",
            "name": "稳享一年定期（模拟）",
            "product_type": "time_deposit",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "2.15",
            "rate_basis": "年化利率，到期一次性还本付息",
            "annual_fee": "0.00",
            "minimum_amount": "1000.00",
            "term_months": 12,
            "risk_level": "R1",
            "liquidity": "medium",
            "features": ["12 个月", "到期还本付息", "低风险"],
            "eligibility": "个人客户，起存 1,000 元",
            "tags": ["定期", "一年", "稳健", "低风险"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-LOAN-001",
            "name": "随心消费贷（模拟）",
            "product_type": "loan",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "4.80",
            "rate_basis": "年化单利示例，实际以审批结果为准",
            "annual_fee": "0.00",
            "minimum_amount": "10000.00",
            "term_months": 12,
            "risk_level": "R2",
            "liquidity": "not_applicable",
            "features": ["用途限定消费", "示例期限 12 个月", "按月还款"],
            "eligibility": "通过模拟授信审查的个人客户",
            "tags": ["消费贷", "借款", "短期", "利率"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-LOAN-002",
            "name": "安居按揭贷（模拟）",
            "product_type": "loan",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "3.85",
            "rate_basis": "年化单利示例，实际以审批结果为准",
            "annual_fee": "0.00",
            "minimum_amount": "100000.00",
            "term_months": 240,
            "risk_level": "R2",
            "liquidity": "not_applicable",
            "features": ["住房按揭", "示例期限 240 个月", "按月还款"],
            "eligibility": "符合模拟住房贷款条件的个人客户",
            "tags": ["房贷", "按揭", "长期", "利率"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-CARD-001",
            "name": "标准白金信用卡（模拟）",
            "product_type": "credit_card",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "18.25",
            "rate_basis": "循环信用年化利率示例",
            "annual_fee": "300.00",
            "minimum_amount": "0.00",
            "term_months": None,
            "risk_level": "R2",
            "liquidity": "high",
            "features": ["年费 300 元", "循环信用", "积分权益"],
            "eligibility": "通过模拟信用卡审批的个人客户",
            "tags": ["信用卡", "年费", "循环信用", "消费"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-FUND-001",
            "name": "现金管理货币基金（模拟）",
            "product_type": "fund",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "1.90",
            "rate_basis": "近 7 日年化收益率示例，不保证未来收益",
            "annual_fee": "0.20",
            "minimum_amount": "1.00",
            "term_months": None,
            "risk_level": "R2",
            "liquidity": "high",
            "features": ["低波动", "T+1 赎回", "不保本"],
            "eligibility": "完成风险测评的个人客户",
            "tags": ["基金", "货币基金", "稳健", "流动性", "低风险"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-FUND-002",
            "name": "稳健配置混合基金（模拟）",
            "product_type": "fund",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "4.50",
            "rate_basis": "业绩比较基准示例，不保证收益",
            "annual_fee": "1.00",
            "minimum_amount": "1000.00",
            "term_months": None,
            "risk_level": "R3",
            "liquidity": "medium",
            "features": ["股债混合", "中低波动", "不保本"],
            "eligibility": "风险承受能力匹配的客户",
            "tags": ["基金", "混合基金", "稳健", "中长期"],
            "source_updated_at": "2026-10-20",
        },
        {
            "product_id": "PROD-FUND-003",
            "name": "全球股票型基金（模拟）",
            "product_type": "fund",
            "provider": "MockBank 模拟产品目录",
            "currency": "CNY",
            "indicative_rate_percent": "7.00",
            "rate_basis": "长期收益示例，不保证收益，波动较高",
            "annual_fee": "1.50",
            "minimum_amount": "1000.00",
            "term_months": None,
            "risk_level": "R4",
            "liquidity": "medium",
            "features": ["全球股票", "高波动", "不保本"],
            "eligibility": "风险承受能力较高的客户",
            "tags": ["基金", "股票基金", "全球", "长期", "高波动"],
            "source_updated_at": "2026-10-20",
        },
    )

    def __init__(self) -> None:
        self._by_id = {item["product_id"]: item for item in self.PRODUCTS}

    def types(self) -> tuple[str, ...]:
        return tuple(sorted({item["product_type"] for item in self.PRODUCTS}))

    def get(self, product_id: str) -> dict[str, Any] | None:
        item = self._by_id.get(product_id)
        return deepcopy(item) if item else None

    def search(
        self,
        *,
        product_type: str | None,
        query: str | None,
        max_results: int,
    ) -> list[dict[str, Any]]:
        query_text = (query or "").strip().casefold()
        tokens = query_terms(query or "")
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in self.PRODUCTS:
            if product_type and item["product_type"] != product_type:
                continue
            score = 0
            if query_text:
                haystack = " ".join(
                    [
                        item["name"],
                        item["rate_basis"],
                        item["eligibility"],
                        " ".join(item["features"]),
                        " ".join(item["tags"]),
                    ]
                ).casefold()
                matched_terms = {
                    token for token in tokens if token in haystack
                }
                minimum_matches = 1 if len(tokens) <= 1 else 2
                if (
                    not matched_terms
                    or (
                        query_text not in haystack
                        and len(matched_terms) < minimum_matches
                    )
                ):
                    continue
                if query_text in haystack:
                    score += 10
                score += 3 * len(matched_terms)
                score += sum(
                    4 for token in tokens if token in {
                        tag.casefold() for tag in item["tags"]
                    }
                )
            scored.append((score, item))
        scored.sort(
            key=lambda pair: (
                -pair[0] if query_text else 0,
                pair[1]["product_id"],
            )
        )
        return [deepcopy(item) for _, item in scored[:max_results]]


class PolicyCorpus:
    """Small local policy corpus with deterministic keyword retrieval.

    This is not the team's production RAG service. It exists so the agent can
    practise citation-grounded answers. Retrieved text is marked as untrusted
    reference material and can never trigger tool calls.
    """

    POLICIES: tuple[dict[str, Any], ...] = (
        {
            "policy_id": "POL-TRANSFER-2026",
            "title": "个人转账与限额政策",
            "category": "transfers",
            "version": "2.0.0",
            "effective_from": "2026-07-01",
            "effective_to": None,
            "source": "MockBank 政策库（模拟）",
            "tags": ["转账", "限额", "单笔", "日累计", "收款人", "审批"],
            "sections": [
                {
                    "section": "限额规则",
                    "text": "单笔转账上限为 50,000.00 元，单日累计转账上限为 100,000.00 元。限额参数由版本化策略配置决定，前端展示不得替代服务端校验。",
                },
                {
                    "section": "确认与复核",
                    "text": "转账提交前需要进行预览、用户确认与提交前重新校验；预览失效或账户状态变化时应停止提交并重新发起。",
                },
            ],
        },
        {
            "policy_id": "POL-TRANSFER-2025",
            "title": "个人转账限额政策（旧版）",
            "category": "transfers",
            "version": "1.0.0",
            "effective_from": "2025-01-01",
            "effective_to": "2026-06-30",
            "source": "MockBank 政策库（模拟，历史版本）",
            "tags": ["转账", "限额", "旧版", "历史"],
            "sections": [
                {
                    "section": "限额规则",
                    "text": "旧版单笔转账上限为 30,000.00 元，单日累计上限为 60,000.00 元。该版本已于 2026-06-30 失效。",
                }
            ],
        },
        {
            "policy_id": "POL-DEPOSIT-2026",
            "title": "存款保险与账户说明",
            "category": "deposits",
            "version": "3.1.0",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "source": "MockBank 政策库（模拟）",
            "tags": ["存款", "保险", "保障", "活期", "定期", "提前支取"],
            "sections": [
                {
                    "section": "保障范围",
                    "text": "本原型中的存款产品与保险说明均为模拟信息，不构成真实存款保险承诺。真实产品应依据监管规定及正式协议执行。",
                },
                {
                    "section": "定期提前支取",
                    "text": "定期存款提前支取可能按活期利率计息，具体规则以产品条款和办理页面展示为准。",
                },
            ],
        },
        {
            "policy_id": "POL-LOAN-2026",
            "title": "个人贷款提前还款与费用说明",
            "category": "loans",
            "version": "2.2.0",
            "effective_from": "2026-03-01",
            "effective_to": None,
            "source": "MockBank 政策库（模拟）",
            "tags": ["贷款", "提前还款", "违约金", "利率", "月供", "按揭"],
            "sections": [
                {
                    "section": "提前还款",
                    "text": "提前还款是否需要预约、是否收取违约金以及最低还款金额，应以具体贷款合同和当期政策为准。本模拟政策不承诺免收费用。",
                },
                {
                    "section": "利率与月供",
                    "text": "示例月供由确定性摊还公式计算，实际月供可能因放款日、计息方式和利率调整而变化。",
                },
            ],
        },
        {
            "policy_id": "POL-CARD-2026",
            "title": "卡片挂失与冻结说明",
            "category": "cards",
            "version": "1.4.0",
            "effective_from": "2026-04-01",
            "effective_to": None,
            "source": "MockBank 政策库（模拟）",
            "tags": ["信用卡", "借记卡", "冻结", "挂失", "丢卡", "安全"],
            "sections": [
                {
                    "section": "冻结流程",
                    "text": "发现卡片遗失后应及时冻结卡片。冻结操作会改变卡片状态，需要用户确认；如需补卡，以正式渠道通知为准。",
                }
            ],
        },
        {
            "policy_id": "POL-FEE-2026",
            "title": "个人服务费率摘要",
            "category": "fees",
            "version": "1.1.0",
            "effective_from": "2026-05-01",
            "effective_to": None,
            "source": "MockBank 政策库（模拟）",
            "tags": ["费用", "年费", "手续费", "管理费", "转账费"],
            "sections": [
                {
                    "section": "转账费用",
                    "text": "本模拟环境的行内转账手续费为 0.00 元。其他产品费用以产品目录的 annual_fee 和正式协议为准。",
                },
                {
                    "section": "信用卡年费",
                    "text": "信用卡年费属于产品定价，不等于利息。费用是否可减免应依据具体产品条款，不应由 Agent 自行推断。",
                },
            ],
        },
        {
            "policy_id": "POL-INVEST-2026",
            "title": "投资产品风险提示",
            "category": "investments",
            "version": "1.0.0",
            "effective_from": "2026-06-01",
            "effective_to": None,
            "source": "MockBank 政策库（模拟）",
            "tags": ["投资", "基金", "风险", "收益", "不保本", "适当性"],
            "sections": [
                {
                    "section": "风险提示",
                    "text": "基金等投资产品不保本，历史收益或业绩比较基准不代表未来表现。任何收益测算均为情景展示，不构成投资建议。",
                }
            ],
        },
        {
            "policy_id": "POL-PRIVACY-2026",
            "title": "个人金融信息使用说明",
            "category": "privacy",
            "version": "2.0.0",
            "effective_from": "2026-02-01",
            "effective_to": None,
            "source": "MockBank 政策库（模拟）",
            "tags": ["隐私", "个人信息", "数据", "授权", "日志"],
            "sections": [
                {
                    "section": "信息最小化",
                    "text": "查询与日志仅保留完成业务所需的信息，完整卡号、手机号、身份证号和验证码不应写入回复、trace 或工具日志。",
                }
            ],
        },
    )

    def __init__(self) -> None:
        self._by_id = {item["policy_id"]: item for item in self.POLICIES}

    def get(self, policy_id: str) -> dict[str, Any] | None:
        item = self._by_id.get(policy_id)
        return deepcopy(item) if item else None

    def search(
        self,
        *,
        query: str,
        category: str | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        query_text = query.strip().casefold()
        tokens = query_terms(query)
        matches: list[dict[str, Any]] = []
        for item in self.POLICIES:
            if category and item["category"] != category:
                continue
            best_section: dict[str, Any] | None = None
            best_score = 0
            for section in item["sections"]:
                haystack = " ".join(
                    [
                        item["title"],
                        " ".join(item["tags"]),
                        section["section"],
                        section["text"],
                    ]
                ).casefold()
                matched_terms = {
                    token for token in tokens if token in haystack
                }
                minimum_matches = 1 if len(tokens) <= 1 else 2
                if (
                    not matched_terms
                    or (
                        query_text not in haystack
                        and len(matched_terms) < minimum_matches
                    )
                ):
                    continue
                score = 0
                if query_text in haystack:
                    score += 8
                score += 3 * len(matched_terms)
                score += sum(
                    4 for token in tokens if token in {
                        tag.casefold() for tag in item["tags"]
                    }
                )
                if score > best_score:
                    best_score = score
                    best_section = section
            if best_section is None or best_score == 0:
                continue
            stale = bool(
                item["effective_to"] and item["effective_to"] < TODAY.isoformat()
            )
            excerpt = best_section["text"]
            if len(excerpt) > 260:
                excerpt = excerpt[:257] + "..."
            matches.append(
                {
                    "policy_id": item["policy_id"],
                    "title": item["title"],
                    "category": item["category"],
                    "version": item["version"],
                    "effective_from": item["effective_from"],
                    "effective_to": item["effective_to"],
                    "source": item["source"],
                    "section": best_section["section"],
                    "excerpt": excerpt,
                    "score": best_score,
                    "citation": f"{item['policy_id']}@{item['version']} §{best_section['section']}",
                    "stale": stale,
                }
            )
        matches.sort(
            key=lambda item: (
                item["stale"],
                -item["score"],
                item["effective_from"],
                item["policy_id"],
            )
        )
        return matches[:top_k]


class PlanningStore:
    """In-memory budgets and alerts. Not durable; restart loses records."""

    def __init__(self) -> None:
        self._budgets: dict[str, dict[str, Any]] = {}
        self._alerts: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save_budget(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._budgets[record["budget_id"]] = deepcopy(record)
        return deepcopy(record)

    def save_alert(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._alerts[record["alert_id"]] = deepcopy(record)
        return deepcopy(record)

    def budgets(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._budgets.values()))

    def alerts(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._alerts.values()))


@dataclass(frozen=True)
class TransactionRequest:
    user_id: str
    session_id: str
    from_account_ref: str
    beneficiary_name: str
    amount: str
    currency: str
    idempotency_key: str
    confirmation_id: str
    note: str = ""


class TransactionGateway(ABC):
    """Downstream payment boundary.

    Module 6 never ships a live implementation. The unavailable gateway fails
    closed; a mock gateway can be injected by tests to exercise the full path.
    """

    adapter_name = "Transaction Gateway"
    adapter_kind = "unconfigured"
    is_connected = False
    is_verified = False
    simulated = True

    def readiness(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter_name,
            "adapter_kind": self.adapter_kind,
            "is_connected": self.is_connected,
            "is_verified": self.is_verified,
            "simulated": self.simulated,
        }

    @abstractmethod
    def execute(self, request: TransactionRequest) -> dict[str, Any]:
        raise NotImplementedError


class UnavailableTransactionGateway(TransactionGateway):
    def execute(self, request: TransactionRequest) -> dict[str, Any]:
        raise ToolLayerError(
            TRANSACTION_GATEWAY_UNAVAILABLE,
            "真实交易网关尚未接通，模拟交易也不会被冒充为真实执行。",
        )


class MockBankTransactionGateway(TransactionGateway):
    """TEST/DEMO ONLY. Reuses the existing in-memory MockBank transfer handler.

    This class deliberately does not implement a real payment gateway or the
    completed Risk Engine/Compliance Guard. Every receipt is marked simulated.
    """

    adapter_name = "MockBank Transaction Gateway"
    adapter_kind = "mock"
    is_connected = True
    is_verified = False
    simulated = True

    def __init__(self, bank: MockBank) -> None:
        self.bank = bank
        self._legacy_registry = ExistingToolRegistry(bank)
        self._handler = self._legacy_registry.get("transfer_funds").handler

    def execute(self, request: TransactionRequest) -> dict[str, Any]:
        if request.currency != "CNY":
            raise ToolLayerError(
                "UNSUPPORTED_ACCOUNT",
                "模拟转账仅支持 CNY。",
            )
        result = self._handler(
            customer_id=request.user_id,
            from_account=request.from_account_ref,
            beneficiary_name=request.beneficiary_name,
            amount=request.amount,
            idempotency_key=request.idempotency_key,
        )
        result = deepcopy(result)
        result["simulated"] = True
        result["gateway"] = self.adapter_name
        result["gateway_adapter_kind"] = self.adapter_kind
        result["note"] = request.note
        return result


@dataclass
class ToolServices:
    bank: MockBank
    bank_access: MockBankService
    products: ProductCatalog
    policies: PolicyCorpus
    planning: PlanningStore
    transaction_gateway: TransactionGateway

    @classmethod
    def demo(cls) -> "ToolServices":
        bank = MockBank()
        return cls(
            bank=bank,
            bank_access=MockBankService(bank),
            products=ProductCatalog(),
            policies=PolicyCorpus(),
            planning=PlanningStore(),
            transaction_gateway=UnavailableTransactionGateway(),
        )

    def with_mock_transaction_gateway(self) -> "ToolServices":
        """Explicit test/demo helper; no caller can mistake this for live."""
        self.transaction_gateway = MockBankTransactionGateway(self.bank)
        return self
