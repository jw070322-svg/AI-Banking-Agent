"""Small deterministic helpers shared by the Tool Calling Layer."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from typing import Any

from ..models import new_id, utc_now

MONEY_QUANT = Decimal("0.01")
RATIO_QUANT = Decimal("0.0001")
PERCENT_QUANT = Decimal("0.01")


def new_call_id() -> str:
    return new_id("CALL")


def new_evidence_id() -> str:
    return new_id("EVD")


def to_decimal(value: Any, *, field: str = "value") -> Decimal:
    """Parse a finite Decimal without silently accepting floats' binary noise."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a decimal value")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a decimal value") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def money(value: Any) -> Decimal:
    return to_decimal(value, field="amount").quantize(
        MONEY_QUANT, rounding=ROUND_HALF_UP
    )


def money_text(value: Any) -> str:
    return f"{money(value):.2f}"


def ratio_text(value: Any) -> str:
    return f"{to_decimal(value, field='ratio').quantize(RATIO_QUANT, rounding=ROUND_HALF_UP):.4f}"


def percent_text(value: Any) -> str:
    return f"{to_decimal(value, field='percent').quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP):.2f}"


def clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def canonical_json(value: Any) -> str:
    """Canonical JSON for hashes and idempotency fingerprints."""
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def jsonable(value: Any) -> Any:
    """Public deep conversion used in trace/evidence payloads."""
    return _jsonable(value)


def deep_copy_json(value: Any) -> Any:
    """Copy through canonical JSON so callers cannot mutate stored results."""
    return json.loads(canonical_json(value))


def now_iso() -> str:
    return utc_now()


def display_date(value: date) -> str:
    return value.isoformat()


def query_terms(query: str) -> list[str]:
    """Deterministic keyword terms with basic CJK bigram support.

    Chinese phrases such as "转账限额" are not whitespace-delimited. Adding
    two-character n-grams lets the local catalogue/policy search match
    separated tags without introducing a probabilistic retriever.
    """
    normalized = (query or "").strip().casefold()
    if not normalized:
        return []
    segments = re.findall(r"[一-鿿]+|[a-z0-9]+", normalized)
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    for segment in segments:
        add(segment)
        if len(segment) > 2 and re.fullmatch(r"[一-鿿]+", segment):
            for index in range(len(segment) - 1):
                add(segment[index : index + 2])
    return terms
