"""Shared contracts, eligibility policy, and explicitly fictional demonstration data.

Design rationale: validate facts before scoring. Missing critical facts cannot be
inferred from popularity. Policy thresholds are prototype assumptions, not law.
All monetary amounts are CNY; durations are calendar days; fee_pct uses percent
units (0.35 means 0.35%, not 35%). Products are alternatives, not a portfolio.
"""
from __future__ import annotations

import math
from numbers import Real

POLICY_VERSION = "demo-policy-1.0"
OBJECTIVES = {"liquidity", "income", "growth"}
CATEGORIES = {"cash", "fixed_income", "balanced", "equity"}


def _number(value, minimum=0, maximum=None, integer=False):
    """Reject bools, strings, NaN, infinities, and values outside the contract."""
    return (isinstance(value, Real) and not isinstance(value, bool)
            and math.isfinite(value) and value >= minimum
            and (maximum is None or value <= maximum)
            and (not integer or float(value).is_integer()))


def _identifier(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def validate_top_k(top_k):
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")


def validate_catalog(products):
    """Fail ambiguous catalog identity; per-product factual errors are excluded."""
    if not isinstance(products, list):
        raise ValueError("products must be a list")
    seen = set()
    for product in products:
        if not isinstance(product, dict) or not _identifier(product.get("product_id")):
            raise ValueError("Each product needs a nonblank string product_id")
        if product["product_id"] in seen:
            raise ValueError("Duplicate product_id: " + product["product_id"])
        seen.add(product["product_id"])


def profile_errors(user):
    """Report critical missing/invalid facts without filling them with averages."""
    if not isinstance(user, dict):
        return ["profile must be an object"]
    errors = []
    if not _identifier(user.get("user_id")):
        errors.append("profile: missing or invalid user_id")
    for key in ("risk_tolerance", "risk_capacity"):
        if not _number(user.get(key), 1, 5, integer=True):
            errors.append("profile: missing or invalid " + key)
    for key in ("budget_cny", "horizon_days", "max_redemption_days"):
        if not _number(user.get(key), integer=(key != "budget_cny")):
            errors.append("profile: missing or invalid " + key)
    if not isinstance(user.get("objective"), str) or user["objective"] not in OBJECTIVES:
        errors.append("profile: missing or invalid objective")
    preferences = user.get("preferred_categories")
    if preferences is not None and (not isinstance(preferences, list) or any(
            not isinstance(x, str) or x not in CATEGORIES for x in preferences)):
        errors.append("profile: invalid preferred_categories")
    return errors


def evaluate_eligibility(user, product):
    """Return hard-gate decisions and reasons; never mutate caller records.

    Risk capacity and willingness are distinct. Their minimum is the cap. A
    growth objective or a past high rating cannot increase it. Duration checks
    conservatively add lockup and redemption delay, in calendar days.
    """
    reasons = profile_errors(user)
    warnings = []
    effective_risk = None
    if not reasons:
        effective_risk = min(user["risk_tolerance"], user["risk_capacity"])
        if user["risk_tolerance"] != user["risk_capacity"]:
            warnings.append("Conflicting risk signals: the lower risk value is binding")
        if user.get("preferred_categories") is None:
            warnings.append("No preferred categories supplied; category preference is neutral")
    if not isinstance(product, dict):
        reasons.append("product must be an object")
        return dict(eligible=False, reasons=reasons, warnings=warnings,
                    effective_risk=effective_risk)
    if not _identifier(product.get("product_id")):
        reasons.append("product: missing or invalid product_id")
    if not _identifier(product.get("name")):
        reasons.append("product: missing or invalid name")
    if not _number(product.get("risk_level"), 1, 5, integer=True):
        reasons.append("product: missing or invalid risk_level")
    for key in ("min_investment_cny", "lockup_days", "redemption_days"):
        if not _number(product.get(key), integer=(key != "min_investment_cny")):
            reasons.append("product: missing or invalid " + key)
    if not isinstance(product.get("category"), str) or product["category"] not in CATEGORIES:
        reasons.append("product: missing or invalid category")
    objectives = product.get("objectives")
    if not isinstance(objectives, list) or not objectives or any(
            not isinstance(x, str) or x not in OBJECTIVES for x in objectives):
        reasons.append("product: missing or invalid objectives")
    if product.get("active") is not True:
        reasons.append("product is inactive or active status is unconfirmed")
    if product.get("facts_verified") is not True:
        reasons.append("product facts are unverified")
    if product.get("currency") != "CNY":
        reasons.append("product currency is missing or unsupported (CNY required)")
    fee = product.get("annual_fee_pct")
    if fee is None:
        warnings.append("Annual fee unavailable: no low-fee preference bonus")
    elif not _number(fee, 0, 100):
        reasons.append("product: invalid annual_fee_pct")

    # Only compare facts after their types and presence have been established.
    if not reasons:
        if product["risk_level"] > effective_risk:
            reasons.append("product risk exceeds the effective risk cap")
        if product["min_investment_cny"] > user["budget_cny"]:
            reasons.append("minimum investment exceeds budget")
        if product["lockup_days"] + product["redemption_days"] > user["horizon_days"]:
            reasons.append("lockup plus redemption exceeds investment horizon")
        if product["redemption_days"] > user["max_redemption_days"]:
            reasons.append("redemption delay exceeds liquidity tolerance")
    return dict(eligible=not reasons, reasons=reasons, warnings=warnings,
                effective_risk=effective_risk)


def sample_users():
    """Fictional profiles, including incomplete and conflicting cases."""
    specs = [
        ("U001", 3, 3, 50000, 400, 7, "income", ["fixed_income"]),
        ("U002", 1, 1, 8000, 30, 1, "liquidity", ["cash"]),
        ("U003", 5, 4, 100000, 1095, 7, "growth", ["equity", "balanced"]),
        ("U004", 3, None, 20000, 365, 7, "income", []),
        ("U005", 5, 1, 30000, 30, 1, "growth", ["equity"]),
        ("U006", 3, 3, 60000, 450, 7, "income", ["fixed_income"]),
        ("U007", 2, 2, 40000, 400, 5, "income", ["fixed_income"]),
        ("U008", 3, 3, 80000, 730, 7, "growth", ["balanced"]),
        ("U009", 1, 1, 10000, 60, 1, "liquidity", ["cash"]),
        ("U010", 5, 5, 150000, 1825, 7, "growth", ["equity"]),
    ]
    fields = ("user_id", "risk_tolerance", "risk_capacity", "budget_cny",
              "horizon_days", "max_redemption_days", "objective", "preferred_categories")
    return [dict(zip(fields, row)) for row in specs]


def sample_products():
    """Fictional terms. facts_verified=True means internally accepted demo facts.

    It does not claim issuer verification or real product availability.
    """
    specs = [
        ("P001", "Example Cash Reserve", 1, 1, 0, 1, "cash", ["liquidity"], 0.15, True),
        ("P002", "Example Short Bond", 2, 1000, 90, 2, "fixed_income", ["income"], 0.35, True),
        ("P003", "Example 365-day Income", 2, 10000, 365, 0, "fixed_income", ["income"], 0.0, True),
        ("P004", "Example Balanced Fund", 3, 100, 180, 3, "balanced", ["income", "growth"], 1.2, True),
        ("P005", "Example Equity Fund", 5, 100, 0, 3, "equity", ["growth"], 1.5, True),
        ("P006", "Example Premium Income", 3, 200000, 90, 2, "fixed_income", ["income"], 0.4, True),
        ("P007", "Example Unverified Cash", 1, 1, 0, 0, "cash", ["liquidity"], None, False),
    ]
    fields = ("product_id", "name", "risk_level", "min_investment_cny", "lockup_days",
              "redemption_days", "category", "objectives", "annual_fee_pct", "facts_verified")
    return [dict(zip(fields, row), active=True, currency="CNY") for row in specs]


def sample_history():
    """Fictional explicit preference ratings, not suitability or return labels.

    Sparse interactions are unobserved, not negative labels. U001 is a cold
    user: profile neighbors can supply evidence without U001's own history.
    """
    ratings = {
        "U002": {"P001": 5},
        "U006": {"P001": 3, "P002": 5, "P003": 3, "P004": 4},
        "U007": {"P001": 3, "P002": 5, "P003": 4},
        "U008": {"P001": 2, "P002": 3, "P004": 5},
        "U009": {"P001": 5},
        "U010": {"P001": 1, "P002": 2, "P004": 4, "P005": 5},
    }
    return [{"user_id": uid, "product_id": pid, "rating": rating}
            for uid, products in ratings.items() for pid, rating in products.items()]


if __name__ == "__main__":
    import json
    print(json.dumps({"provenance": "fictional demonstration data, not workbook data",
                      "users": sample_users(), "products": sample_products(),
                      "history": sample_history()}, indent=2, allow_nan=False))
