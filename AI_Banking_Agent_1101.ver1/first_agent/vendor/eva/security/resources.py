"""Server-side resource ownership resolution.

The resolver is the only place that turns an untrusted account/card/plan
reference into an owned resource. It reuses the existing `MockBank` lookup
methods rather than re-implementing account matching rules.

For advisor/shared/break-glass access, the authorization service supplies the
candidate owner IDs. The resolver only returns a resource whose owner is in that
server-provided candidate set, so a client-supplied owner hint can never widen
access.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from ..models import ToolError
from .models import ResolvedResource, ResourceRef


class ResourceResolver(ABC):
    @abstractmethod
    def resolve(
        self, resource: ResourceRef, owner_candidates: Iterable[str]
    ) -> ResolvedResource | None:
        raise NotImplementedError

    def owned_account_ids(self, user_id: str) -> set[str]:
        return set()

    def all_account_ids(self) -> set[str]:
        return set()


class MockBankResourceResolver(ResourceResolver):
    """Ownership resolution backed by the existing in-memory MockBank.

    `planning_store` is optional and may be the Module 6 `PlanningStore`
    (budgets/alerts). It is read through public methods only.
    """

    def __init__(self, bank: Any, planning_store: Any | None = None) -> None:
        self.bank = bank
        self.planning_store = planning_store

    def resolve(
        self, resource: ResourceRef, owner_candidates: Iterable[str]
    ) -> ResolvedResource | None:
        candidates = [owner for owner in owner_candidates if owner]
        if not candidates:
            return None
        kind = (resource.type or "").strip().lower()
        ref = (resource.id or "").strip()
        if not ref:
            return None

        if kind == "account":
            matches = self._find_accounts(candidates, ref)
            return self._single(matches, "account", ref)

        if kind == "card":
            matches = []
            for owner in candidates:
                try:
                    card = self.bank.find_card(owner, ref)
                except ToolError:
                    continue
                matches.append(
                    ResolvedResource(
                        type="card",
                        resource_id=card["card_id"],
                        owner_id=card["customer_id"],
                        label=f"{card['type']}（尾号 {card['last4']}）",
                        metadata={"last4": card["last4"], "status": card["status"]},
                    )
                )
            return self._single(matches, "card", ref)

        if kind == "beneficiary":
            matches = []
            for owner in candidates:
                try:
                    beneficiary = self.bank.find_beneficiary(owner, ref)
                except ToolError:
                    continue
                matches.append(
                    ResolvedResource(
                        type="beneficiary",
                        resource_id=beneficiary["beneficiary_id"],
                        owner_id=beneficiary["customer_id"],
                        label=beneficiary["name"],
                        metadata={
                            "bank": beneficiary.get("bank", ""),
                            "last4": beneficiary.get("account_last4", ""),
                        },
                    )
                )
            return self._single(matches, "beneficiary", ref)

        if kind == "transaction":
            for tx in getattr(self.bank, "transactions", []):
                if tx.get("tx_id") != ref:
                    continue
                account = self.bank.accounts.get(tx.get("account_id"))
                if account and account["customer_id"] in candidates:
                    return ResolvedResource(
                        type="transaction",
                        resource_id=tx["tx_id"],
                        owner_id=account["customer_id"],
                        label=f"交易 {tx['tx_id']}",
                        metadata={"account_id": account["account_id"]},
                    )
            return None

        if kind in {"plan", "alert"}:
            return self._resolve_planning(kind, ref, candidates)

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_accounts(
        self, candidates: list[str], ref: str
    ) -> list[ResolvedResource]:
        matches: list[ResolvedResource] = []
        seen: set[str] = set()
        for owner in candidates:
            try:
                account = self.bank.find_account(owner, ref)
            except ToolError:
                continue
            if account["account_id"] in seen:
                continue
            seen.add(account["account_id"])
            matches.append(
                ResolvedResource(
                    type="account",
                    resource_id=account["account_id"],
                    owner_id=account["customer_id"],
                    label=f"{account['type']}（尾号 {account['last4']}）",
                    metadata={
                        "last4": account["last4"],
                        "kind": account["kind"],
                        "status": account["status"],
                    },
                )
            )
        return matches

    @staticmethod
    def _single(
        matches: list[ResolvedResource], kind: str, ref: str
    ) -> ResolvedResource | None:
        # An ambiguous reference (e.g. the same last4 for two owners) is not
        # resolved. The caller returns a generic not-found decision.
        if len(matches) == 1:
            return matches[0]
        return None

    def _resolve_planning(
        self, kind: str, ref: str, candidates: list[str]
    ) -> ResolvedResource | None:
        if self.planning_store is None:
            return None
        if kind == "plan":
            records = self.planning_store.budgets()
            id_field = "budget_id"
        else:
            records = self.planning_store.alerts()
            id_field = "alert_id"
        for record in records:
            if str(record.get(id_field)) != ref:
                continue
            owner = str(record.get("user_id") or "")
            if owner in candidates:
                return ResolvedResource(
                    type=kind,
                    resource_id=ref,
                    owner_id=owner,
                    label=str(record.get("name") or ref),
                    metadata={"persistence_mode": record.get("persistence_mode")},
                )
        return None

    def owned_account_ids(self, user_id: str) -> set[str]:
        return {
            account_id
            for account_id, account in self.bank.accounts.items()
            if account["customer_id"] == user_id
        }

    def all_account_ids(self) -> set[str]:
        return set(self.bank.accounts)
