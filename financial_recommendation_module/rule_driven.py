"""Transparent financial-product preference ranking over validated facts.

Architecture: shared factual eligibility checks run first, then a versioned,
expert-authored preference rubric ranks eligible alternatives. The rubric and
thresholds below are demonstration policy assumptions, not legal requirements
or investment advice. Scores describe preference alignment, not expected
returns or probabilities of suitability. No external packages are required.

The default profiles/products are fictional placeholders. This module makes no
claim that they were extracted from EDE20261017.xlsx. Supply normalized data
with --input when a reviewed workbook mapping is available.

Usage: python rule_driven.py --user-id U001 --top-k 3
       python rule_driven.py --input normalized_input.json --user-id U001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from matching_core import (
    POLICY_VERSION,
    evaluate_eligibility,
    profile_errors,
    sample_products,
    sample_users,
    validate_catalog,
    validate_top_k,
)

RULE_VERSION = "demo-preference-rules-1.0"
LOW_FEE_THRESHOLD_PCT = 0.5  # Percent units: 0.5 means 0.5% per year.

# Priorities are encoded in bounded contributions: 60 > 25+10+5 and 25 > 10+5.
# Thus a lower-priority preference cannot outweigh an objective/category match.
# Within the final priority tier, access speed and known fees trade off by points.
# No soft rule can override rejection by matching_core.evaluate_eligibility.
RULE_CORPUS = (
    {"rule_id": "R010", "priority": 1, "max_contribution": 60.0,
     "description": "Product objectives include the user's stated objective"},
    {"rule_id": "R020", "priority": 2, "max_contribution": 25.0,
     "description": "Product category is explicitly preferred by the user"},
    {"rule_id": "R030", "priority": 3, "max_contribution": 10.0,
     "description": "Shorter lockup plus redemption relative to the horizon"},
    {"rule_id": "R040", "priority": 3, "max_contribution": 5.0,
     "description": "Known annual fee is at most 0.5 percent"},
)


def _score_preferences(user: dict, product: dict) -> tuple[float, list[dict]]:
    """Score only records that have passed the shared factual safety gate.

    Missing optional preferences are neutral. A missing fee cannot earn a
    low-fee bonus; it is never imputed as zero. More available risk capacity
    does not itself create a preference for a higher-risk product.
    """
    duration = product["lockup_days"] + product["redemption_days"]
    horizon = user["horizon_days"]
    # A zero-day horizon only admits a zero-day total duration at the gate.
    flexibility = 1.0 if horizon == 0 else 1.0 - duration / horizon
    fee = product.get("annual_fee_pct")
    conditions = (
        user["objective"] in product["objectives"],
        product["category"] in (user.get("preferred_categories") or []),
        True,
        fee is not None and fee <= LOW_FEE_THRESHOLD_PCT,
    )
    contributions = (
        60.0 if conditions[0] else 0.0,
        25.0 if conditions[1] else 0.0,
        round(10.0 * max(0.0, min(1.0, flexibility)), 6),
        5.0 if conditions[3] else 0.0,
    )
    facts = (
        {"user_objective": user["objective"], "product_objectives": list(product["objectives"])},
        {"preferred_categories": list(user.get("preferred_categories") or []),
         "product_category": product["category"]},
        {"total_access_days": duration, "horizon_days": horizon},
        {"annual_fee_pct": fee, "threshold_pct": LOW_FEE_THRESHOLD_PCT},
    )
    evidence = [
        dict(rule, matched=matched, contribution=contribution, facts=observed)
        for rule, matched, contribution, observed in zip(
            RULE_CORPUS, conditions, contributions, facts)
    ]
    return round(sum(contributions), 6), evidence


def recommend(user: dict, products: list[dict], top_k: int = 3) -> dict:
    """Return deterministic rankings, explicit exclusions, and rule evidence.

    Input records are not mutated. Bad catalog identities or top_k raise
    ValueError. Incomplete/invalid profiles abstain with needs_profile_completion;
    defective product facts exclude only the affected product. All scores use
    the same fixed scale [0, 100], with product_id ascending to resolve ties.
    Products are independent alternatives; this is not a portfolio allocator.
    """
    validate_top_k(top_k)
    validate_catalog(products)
    errors = profile_errors(user)
    result = {
        "module": "rule_driven",
        "method": "prioritized_expert_preference_rules",
        "policy_version": POLICY_VERSION,
        "rule_version": RULE_VERSION,
        "user_id": user.get("user_id") if isinstance(user, dict) else None,
        "status": "needs_profile_completion" if errors else "no_eligible_products",
        "score_meaning": "Preference rubric points (0-100), not a probability or return",
        "recommendations": [],
        "excluded": [],
        "warnings": list(errors),
    }
    if errors:
        return result

    # Profile warnings are still useful when the product catalog is empty.
    if user["risk_tolerance"] != user["risk_capacity"]:
        result["warnings"].append(
            "Conflicting risk signals: the lower risk value is binding")
    if user.get("preferred_categories") is None:
        result["warnings"].append(
            "No preferred categories supplied; category preference is neutral")

    candidates = []
    for product in products:
        gate = evaluate_eligibility(user, product)
        for warning in gate["warnings"]:
            # Keep per-product fee provenance, while deduplicating profile notes.
            note = (f"{product['product_id']}: {warning}"
                    if warning.startswith("Annual fee") else warning)
            if note not in result["warnings"]:
                result["warnings"].append(note)
        if not gate["eligible"]:
            result["excluded"].append({"product_id": product["product_id"],
                                       "reasons": gate["reasons"]})
            continue
        score, evidence = _score_preferences(user, product)
        candidates.append({
            "product_id": product["product_id"],
            "product_name": product["name"],
            "score": score,
            "objective_match": user["objective"] in product["objectives"],
            "effective_risk_cap": gate["effective_risk"],
            "rule_evidence": evidence,
            "eligibility_notes": gate["warnings"],
        })
    candidates.sort(key=lambda item: (-item["score"], item["product_id"]))
    result["recommendations"] = candidates[:top_k]
    result["excluded"].sort(key=lambda item: item["product_id"])
    result["warnings"].sort()
    if candidates:
        result["status"] = "ok"
        if not any(item["objective_match"] for item in candidates):
            result["warnings"].append(
                "No eligible product matches the stated objective; results are "
                "eligible alternatives, not objective matches")
    return result


def main(argv: list[str] | None = None) -> int:
    """Read a normalized {users: [...], products: [...]} JSON document."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Normalized JSON input path")
    parser.add_argument("--user-id", default="U001", help="Profile to match (default: U001)")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        if args.input:
            payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
            source = "caller_supplied_normalized_json; provenance not independently verified"
        else:
            payload = {"users": sample_users(), "products": sample_products()}
            source = "fictional demonstration data; not extracted from EDE20261017.xlsx"
        if not isinstance(payload, dict):
            raise ValueError("Input must be a JSON object with users and products")
        users = payload.get("users")
        if not isinstance(users, list) or any(not isinstance(u, dict) for u in users):
            raise ValueError("users must be a list of objects")
        selected = [u for u in users if u.get("user_id") == args.user_id]
        if len(selected) != 1:
            raise ValueError("--user-id must identify exactly one profile")
        output = recommend(selected[0], payload.get("products"), args.top_k)
        output["data_source"] = source
        print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
