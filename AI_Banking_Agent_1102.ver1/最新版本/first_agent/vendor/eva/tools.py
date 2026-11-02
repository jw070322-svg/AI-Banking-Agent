"""银行工具层：对核心系统的唯一访问入口。

真实项目里，把这里的内存读写替换成核心系统 / 支付网关 API 即可，
上层的意图、规划、选择、执行、校验逻辑不需要修改。
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from .data import CNY, POLICY, TODAY, D, MockBank
from .models import ALLOWED_SCOPES, ToolError, ToolSpec, new_id, utc_now
from .utils import fmt_money


class ToolRegistry:
    def __init__(self, bank: MockBank):
        self.bank = bank
        self._specs: dict[str, ToolSpec] = {}
        self._register()

    # ---------- 注册 ----------

    def _add(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"重复注册工具：{spec.name}")
        if spec.risk_tier not in {"R0", "R1", "R2", "R3", "R4"}:
            raise ValueError(f"工具 {spec.name} 的风险等级非法：{spec.risk_tier}")
        if spec.mutating and spec.risk_tier not in {"R3", "R4"}:
            raise ValueError(
                f"变更类工具 {spec.name} 的风险等级不能低于 R3。"
            )
        if spec.risk_tier == "R4" and not spec.requires_step_up:
            raise ValueError(f"R4 工具 {spec.name} 必须声明 requires_step_up。")
        if not spec.scopes:
            raise ValueError(f"工具 {spec.name} 未声明 scope，默认拒绝注册。")
        unknown_scopes = set(spec.scopes) - ALLOWED_SCOPES
        if unknown_scopes:
            raise ValueError(
                f"工具 {spec.name} 声明了未知 scope：{sorted(unknown_scopes)}"
            )
        self._specs[spec.name] = spec

    def _register(self) -> None:
        self._add(
            ToolSpec(
                name="get_account_balance",
                description="查询当前客户名下的账户余额 / 信用卡额度。",
                required_args=("customer_id", "account_ref"),
                handler=self._get_account_balance,
                risk_tier="R1",
                version="1.0.0",
                scopes=("account:read",),
            )
        )
        self._add(
            ToolSpec(
                name="query_transactions",
                description="查询指定账户最近 N 天的交易流水，并按类别汇总支出。",
                required_args=("customer_id", "account_ref"),
                handler=self._query_transactions,
                risk_tier="R1",
                version="1.0.0",
                scopes=("transactions:read",),
            )
        )
        self._add(
            ToolSpec(
                name="check_transfer_limits",
                description="转账前置校验：账户归属、余额、单笔/当日限额、收款人白名单。",
                required_args=("customer_id", "account_ref", "beneficiary_name", "amount"),
                handler=self._check_transfer_limits,
                risk_tier="R3",
                version="1.0.0",
                scopes=("transfer:write",),
            )
        )
        self._add(
            ToolSpec(
                name="transfer_funds",
                description="执行转账并扣减账户余额。资金变动类工具，必须二次确认。",
                required_args=(
                    "customer_id",
                    "from_account",
                    "beneficiary_name",
                    "amount",
                    "idempotency_key",
                ),
                handler=self._transfer_funds,
                mutating=True,
                inject_idempotency_key=True,
                risk_tier="R4",
                version="1.0.0",
                requires_step_up=True,
                scopes=("transfer:write",),
            )
        )
        self._add(
            ToolSpec(
                name="get_card_status",
                description="查询银行卡状态。",
                required_args=("customer_id", "card_ref"),
                handler=self._get_card_status,
                risk_tier="R1",
                version="1.0.0",
                scopes=("card:read",),
            )
        )
        self._add(
            ToolSpec(
                name="freeze_card",
                description="冻结银行卡。资金变动类安全操作，必须二次确认。",
                required_args=("customer_id", "card_ref"),
                handler=self._freeze_card,
                mutating=True,
                inject_idempotency_key=True,
                risk_tier="R3",
                version="1.0.0",
                scopes=("card:write",),
            )
        )
        self._add(
            ToolSpec(
                name="get_loan_status",
                description="查询贷款余额、月供和下一还款日。",
                required_args=("customer_id",),
                handler=self._get_loan_status,
                risk_tier="R1",
                version="1.0.0",
                scopes=("loan:read",),
            )
        )

    # ---------- 注册表接口 ----------

    def get(self, name: str) -> ToolSpec:
        return self._specs[name]

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def names(self) -> list[str]:
        return list(self._specs)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "required_args": list(spec.required_args),
                "mutating": spec.mutating,
                "risk_tier": spec.risk_tier,
                "version": spec.version,
                "requires_step_up": spec.requires_step_up,
                "scopes": list(spec.scopes),
            }
            for spec in self._specs.values()
        ]

    # ---------- 通用校验 ----------

    def _validate_transfer(
        self,
        customer_id: str,
        from_account: str,
        beneficiary_name: str,
        amount: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], Decimal]:
        account = self.bank.find_account(customer_id, from_account)
        beneficiary = self.bank.find_beneficiary(customer_id, beneficiary_name)
        transfer_amount = D(amount)

        if transfer_amount <= 0:
            raise ToolError("INVALID_ARGUMENT", "转账金额必须大于 0。")
        if account["kind"] != "debit":
            raise ToolError(
                "UNSUPPORTED_ACCOUNT",
                "信用卡不支持转出，请选择储蓄卡或工资卡。",
            )
        if account["status"] != "active":
            raise ToolError("POLICY_DENIED", "转出账户当前不可用。")

        reasons: list[str] = []
        if transfer_amount > POLICY["single_transfer_limit_cny"]:
            reasons.append(
                f"单笔转账上限为 {fmt_money(POLICY['single_transfer_limit_cny'])}"
            )
        if transfer_amount > account["available"]:
            reasons.append(
                f"账户可用余额不足（可用 {fmt_money(account['available'])}）"
            )

        used = self.bank.daily_transfer_total(customer_id)
        daily_limit = POLICY["daily_transfer_limit_cny"]
        if used + transfer_amount > daily_limit:
            remaining = max(daily_limit - used, D("0.00"))
            reasons.append(f"超出当日累计转账限额（剩余 {fmt_money(remaining)}）")

        if not beneficiary["whitelisted"]:
            reasons.append("收款人不在安全收款人名册中，暂不支持转出")

        if reasons:
            raise ToolError(
                "POLICY_DENIED",
                "；".join(reasons),
                data={"reasons": reasons},
            )

        return account, beneficiary, transfer_amount

    # ---------- 工具实现 ----------

    def _get_account_balance(self, customer_id: str, account_ref: str) -> dict[str, Any]:
        account = self.bank.find_account(customer_id, account_ref)
        base = {
            "account_id": account["account_id"],
            "account_type": account["type"],
            "last4": account["last4"],
            "currency": account["currency"],
            "kind": account["kind"],
            "status": account["status"],
        }
        if account["kind"] == "credit":
            return {
                **base,
                "credit_limit": str(account["credit_limit"]),
                "outstanding": str(account["outstanding"]),
                "available_credit": str(account["available_credit"]),
            }
        return {
            **base,
            "balance": str(account["balance"]),
            "available": str(account["available"]),
        }

    def _query_transactions(
        self,
        customer_id: str,
        account_ref: str,
        days: int = 30,
        category: str | None = None,
    ) -> dict[str, Any]:
        account = self.bank.find_account(customer_id, account_ref)
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise ToolError("INVALID_ARGUMENT", "查询天数必须是整数。")
        if not 1 <= days <= 365:
            raise ToolError("INVALID_ARGUMENT", "查询天数需在 1 到 365 之间。")

        from_date = TODAY.fromordinal(TODAY.toordinal() - days)
        to_date = TODAY

        matched = [
            tx
            for tx in self.bank.transactions
            if tx["account_id"] == account["account_id"]
            and from_date <= TODAY.fromisoformat(tx["date"]) <= to_date
            and (not category or tx["category"] == category)
        ]
        matched.sort(key=lambda tx: (tx["date"], tx["tx_id"]), reverse=True)

        debits = [tx for tx in matched if tx["direction"] == "debit"]
        credits = [tx for tx in matched if tx["direction"] == "credit"]
        total_debit = sum((tx["amount"] for tx in debits), D("0.00"))
        total_credit = sum((tx["amount"] for tx in credits), D("0.00"))

        category_totals: dict[str, dict[str, Any]] = {}
        for tx in debits:
            bucket = category_totals.setdefault(
                tx["category"], {"category": tx["category"], "count": 0, "amount": D("0.00")}
            )
            bucket["count"] += 1
            bucket["amount"] += tx["amount"]

        by_category = [
            {
                "category": bucket["category"],
                "count": bucket["count"],
                "amount": str(bucket["amount"]),
            }
            for bucket in sorted(
                category_totals.values(), key=lambda item: item["amount"], reverse=True
            )
        ]

        return {
            "account_id": account["account_id"],
            "account_type": account["type"],
            "last4": account["last4"],
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "days": days,
            "category_filter": category,
            "transaction_count": len(matched),
            "debit_count": len(debits),
            "credit_count": len(credits),
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "net": str(total_credit - total_debit),
            "by_category": by_category,
            "transactions": [
                {
                    "tx_id": tx["tx_id"],
                    "date": tx["date"],
                    "merchant": tx["merchant"],
                    "category": tx["category"],
                    "direction": tx["direction"],
                    "amount": str(tx["amount"]),
                }
                for tx in matched[:15]
            ],
        }

    def _check_transfer_limits(
        self,
        customer_id: str,
        account_ref: str,
        beneficiary_name: str,
        amount: Any,
    ) -> dict[str, Any]:
        account, beneficiary, transfer_amount = self._validate_transfer(
            customer_id, account_ref, beneficiary_name, amount
        )
        used = self.bank.daily_transfer_total(customer_id)
        daily_limit = POLICY["daily_transfer_limit_cny"]
        risk_level = (
            "high"
            if transfer_amount >= POLICY["large_amount_reminder_cny"]
            else "medium"
        )

        return {
            "allowed": True,
            "amount": str(transfer_amount),
            "currency": CNY,
            "from_account_id": account["account_id"],
            "from_account_type": account["type"],
            "from_account_last4": account["last4"],
            "available": str(account["available"]),
            "single_limit": str(POLICY["single_transfer_limit_cny"]),
            "daily_used": str(used),
            "daily_limit": str(daily_limit),
            "daily_remaining": str(daily_limit - used),
            "requires_confirmation": True,
            "risk_level": risk_level,
            "beneficiary": {
                "name": beneficiary["name"],
                "bank": beneficiary["bank"],
                "account_last4": beneficiary["account_last4"],
            },
            "fee": str(POLICY["transfer_fee_cny"]),
        }

    def _transfer_funds(
        self,
        customer_id: str,
        from_account: str,
        beneficiary_name: str,
        amount: Any,
        idempotency_key: str,
    ) -> dict[str, Any]:
        key = (idempotency_key or "").strip()
        if not key:
            raise ToolError("INVALID_ARGUMENT", "缺少幂等键，拒绝执行资金变动。")

        cached = self.bank.idempotency.get(key)
        if cached is not None:
            replay = deepcopy(cached)
            replay["duplicate"] = True
            return replay

        account, beneficiary, transfer_amount = self._validate_transfer(
            customer_id, from_account, beneficiary_name, amount
        )

        balance_before = account["balance"]
        balance_after = balance_before - transfer_amount
        account["balance"] = balance_after
        account["available"] = account["available"] - transfer_amount
        self.bank.add_daily_transfer(customer_id, transfer_amount)

        transfer_id = new_id("TRF")
        executed_at = utc_now()
        tx_serial = 90000 + len(self.bank.transactions) + 1
        self.bank.transactions.append(
            {
                "tx_id": f"TX-{tx_serial:05d}",
                "account_id": account["account_id"],
                "date": TODAY.isoformat(),
                "merchant": f"转账-{beneficiary['name']}",
                "category": "转账",
                "direction": "debit",
                "amount": transfer_amount,
                "channel": "手机银行",
            }
        )

        result = {
            "transfer_id": transfer_id,
            "status": "completed",
            "from_account_id": account["account_id"],
            "from_account_type": account["type"],
            "from_account_last4": account["last4"],
            "amount": str(transfer_amount),
            "currency": CNY,
            "fee": str(POLICY["transfer_fee_cny"]),
            "balance_before": str(balance_before),
            "balance_after": str(balance_after),
            "beneficiary": {
                "name": beneficiary["name"],
                "bank": beneficiary["bank"],
                "account_last4": beneficiary["account_last4"],
            },
            "executed_at": executed_at,
            "duplicate": False,
        }
        self.bank.idempotency[key] = deepcopy(result)
        self.bank.record_audit(
            {
                "event": "transfer_executed",
                "customer_id": customer_id,
                "transfer_id": transfer_id,
                "from_account_id": account["account_id"],
                "amount": str(transfer_amount),
                "idempotency_key": key,
                "at": executed_at,
            }
        )
        return result

    def _get_card_status(self, customer_id: str, card_ref: str) -> dict[str, Any]:
        card = self.bank.find_card(customer_id, card_ref)
        return {
            "card_id": card["card_id"],
            "card_type": card["type"],
            "last4": card["last4"],
            "network": card.get("network", "银联"),
            "status": card["status"],
            "status_label": "正常" if card["status"] == "active" else "已冻结",
            "related_account_id": card["account_id"],
            "freeze_reason": card.get("freeze_reason"),
            "frozen_at": card.get("frozen_at"),
        }

    def _freeze_card(
        self,
        customer_id: str,
        card_ref: str,
        reason: str = "客户申请冻结",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        key = (idempotency_key or "").strip()
        if not key:
            raise ToolError("INVALID_ARGUMENT", "缺少幂等键，拒绝执行资金变动。")

        cached = self.bank.idempotency.get(key)
        if cached is not None:
            replay = deepcopy(cached)
            replay["duplicate"] = True
            return replay

        card = self.bank.find_card(customer_id, card_ref)
        already_frozen = card["status"] == "frozen"
        if not already_frozen:
            card["status"] = "frozen"
            card["freeze_reason"] = reason
            card["frozen_at"] = utc_now()

        result = {
            "card_id": card["card_id"],
            "card_type": card["type"],
            "last4": card["last4"],
            "status": card["status"],
            "status_label": "已冻结",
            "reason": card.get("freeze_reason", reason),
            "already_frozen": already_frozen,
            "duplicate": False,
            "executed_at": utc_now(),
        }
        self.bank.idempotency[key] = deepcopy(result)
        self.bank.record_audit(
            {
                "event": "card_frozen",
                "customer_id": customer_id,
                "card_id": card["card_id"],
                "reason": result["reason"],
                "already_frozen": already_frozen,
                "idempotency_key": key,
                "at": result["executed_at"],
            }
        )
        return result

    def _get_loan_status(self, customer_id: str) -> dict[str, Any]:
        loans = self.bank.loans.get(customer_id, [])
        if not loans:
            raise ToolError("INVALID_ARGUMENT", "当前客户名下没有查询到贷款记录。")
        return {
            "customer_id": customer_id,
            "count": len(loans),
            "loans": [
                {
                    "customer_id": loan["customer_id"],
                    "loan_id": loan["loan_id"],
                    "type": loan["type"],
                    "principal": str(loan["principal"]),
                    "outstanding": str(loan["outstanding"]),
                    "annual_rate": loan["annual_rate"],
                    "monthly_payment": str(loan["monthly_payment"]),
                    "next_due_date": loan["next_due_date"],
                    "status": loan["status"],
                }
                for loan in loans
            ],
        }
