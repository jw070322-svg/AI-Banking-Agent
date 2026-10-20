"""Data-driven financial-product preference ranking, with a shared hard gate.

Rationale and algorithm, before the implementation:
1. Validate identities and ratings. Treat missing ratings as unobserved.
2. Exclude the target user's entire history and profile from fitting.
3. Fit numeric feature ranges on valid reference users with observed ratings.
4. Find profile neighbors and aggregate their observed product ratings.
5. Recommend only products that pass the independent factual eligibility gate.

This is an interpretable, memory-based hybrid recommender: profile distance
supports user cold start; the product preference estimates come from observed
interactions. It is NOT a trained suitability classifier or a return forecast.
No labeled interactions means abstention, not an invented prediction. The CLI's
default dataset is explicitly fictional; the Python API never inserts samples.

Only the Python standard library is required. Run from this directory:
    python data_driven.py --user-id U001
    python data_driven.py --input normalized_data.json --user-id U001
    python data_driven.py --evaluate
"""
from __future__ import annotations

import argparse
import json
import math
from numbers import Real
from pathlib import Path

from matching_core import (
    POLICY_VERSION, evaluate_eligibility, profile_errors, sample_history, sample_products,
    sample_users, validate_catalog, validate_top_k,
)

MODEL_VERSION = "profile-neighbor-ratings-1.0"
NUMERIC_FEATURES = (
    "risk_tolerance", "risk_capacity", "budget_cny", "horizon_days",
    "max_redemption_days",
)
LOG_FEATURES = {"budget_cny", "horizon_days", "max_redemption_days"}
NEIGHBOR_LIMIT = 5
MIN_SUPPORT = 2
MAX_DISTANCE = 0.60


def _identifier(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _numeric_value(user, key):
    value = float(user[key])
    return math.log1p(value) if key in LOG_FEATURES else value


def _validate_training_data(reference_users, products, history):
    """Reject ambiguous identities/labels; incomplete peer profiles are skipped.

    Invalid reference profiles are not imputed. They may belong to legitimate
    users awaiting profile completion. History with unknown IDs, duplicate pairs,
    nonfinite ratings, booleans, or out-of-range ratings is a dataset error.
    """
    if not isinstance(reference_users, list) or not isinstance(history, list):
        raise ValueError("reference_users and history must be lists")
    user_by_id = {}
    for user in reference_users:
        if not isinstance(user, dict) or not _identifier(user.get("user_id")):
            raise ValueError("Each reference user needs a nonblank string user_id")
        uid = user["user_id"]
        if uid in user_by_id:
            raise ValueError("Duplicate reference user_id: " + uid)
        user_by_id[uid] = user
    product_ids = {product["product_id"] for product in products}
    seen = set()
    for index, row in enumerate(history):
        if not isinstance(row, dict):
            raise ValueError(f"history[{index}] must be an object")
        uid, pid, rating = row.get("user_id"), row.get("product_id"), row.get("rating")
        if not _identifier(uid) or uid not in user_by_id:
            raise ValueError(f"history[{index}] has an unknown or invalid user_id")
        if not _identifier(pid) or pid not in product_ids:
            raise ValueError(f"history[{index}] has an unknown or invalid product_id")
        if (isinstance(rating, bool) or not isinstance(rating, Real)
                or not math.isfinite(rating) or not 1 <= rating <= 5):
            raise ValueError(f"history[{index}].rating must be finite and within 1..5")
        pair = (uid, pid)
        if pair in seen:
            raise ValueError(f"Duplicate history pair: {uid}/{pid}")
        seen.add(pair)
    return user_by_id


class NeighborRatingModel:
    """Fit a target-specific profile-neighbor model from explicit ratings.

    The arithmetic mean of feature distances defines d in [0, 1]. Numeric
    distances use fitted min/max ranges after log1p for skewed amounts/durations;
    objective is 0/1 and optional categories use Jaccard distance. A constant
    training feature is omitted. Numeric outliers are clipped at distance 1.
    Missing categories omit that optional distance rather than inventing values.

    Select the closest five users with d <= 0.60; break ties by user ID. For each
    product, estimate sum((1-d)*rating)/sum(1-d), using only selected users who
    rated that product. Require two distinct supporting users. All thresholds
    are transparent prototype choices, not tuned or validated production values.
    """

    def __init__(self):
        self.peers = []
        self.ranges = {}
        self.ratings = {}
        self.warnings = []
        self.target_user_id = None
        self.fitted = False

    def fit(self, reference_users, products, history, *, target_user_id):
        """Rebuild fitted state; hold out the target user's complete history."""
        validate_catalog(products)
        if not _identifier(target_user_id):
            raise ValueError("target_user_id must be a nonblank string")
        user_by_id = _validate_training_data(reference_users, products, history)
        self.peers, self.ranges, self.ratings, self.warnings = [], {}, {}, []
        self.fitted = False
        self.target_user_id = target_user_id
        observed_ids = {row["user_id"] for row in history}
        for uid in sorted(observed_ids - {target_user_id}):
            peer = user_by_id[uid]
            errors = profile_errors(peer)
            if errors:
                self.warnings.append(
                    f"Reference user {uid} excluded from fitting: " + "; ".join(errors)
                )
                continue
            self.peers.append(peer)
        valid_ids = {peer["user_id"] for peer in self.peers}
        self.ratings = {
            (row["user_id"], row["product_id"]): float(row["rating"])
            for row in history if row["user_id"] in valid_ids
        }
        for key in NUMERIC_FEATURES:
            values = [_numeric_value(peer, key) for peer in self.peers]
            if values and max(values) > min(values):
                self.ranges[key] = (min(values), max(values))
        self.fitted = True
        return self

    def _distance(self, user, peer):
        terms = []
        for key, (minimum, maximum) in self.ranges.items():
            difference = abs(_numeric_value(user, key) - _numeric_value(peer, key))
            terms.append(min(1.0, difference / (maximum - minimum)))
        terms.append(float(user["objective"] != peer["objective"]))
        left = set(user.get("preferred_categories") or [])
        right = set(peer.get("preferred_categories") or [])
        if left and right:
            terms.append(1.0 - len(left & right) / len(left | right))
        return sum(terms) / len(terms)

    def neighbors(self, user):
        if not self.fitted:
            raise ValueError("Call fit before neighbors")
        errors = profile_errors(user)
        if errors:
            raise ValueError("Cannot calculate neighbors: " + "; ".join(errors))
        if user["user_id"] != self.target_user_id:
            raise ValueError("Refit for this target user to prevent own-history leakage")
        neighbors = []
        for peer in self.peers:
            distance = self._distance(user, peer)
            if distance <= MAX_DISTANCE:
                neighbors.append({"user_id": peer["user_id"], "distance": distance,
                                  "weight": 1.0 - distance})
        return sorted(neighbors, key=lambda item: (item["distance"], item["user_id"]))[
            :NEIGHBOR_LIMIT
        ]

    def predict(self, product_id, neighbors):
        """Return an evidence-bearing preference estimate or an abstention."""
        evidence = []
        for neighbor in neighbors:
            rating = self.ratings.get((neighbor["user_id"], product_id))
            if rating is not None:
                evidence.append(dict(neighbor, rating=rating))
        weight_sum = sum(row["weight"] for row in evidence)
        score = None
        if len(evidence) >= MIN_SUPPORT and weight_sum > 0:
            score = sum(row["weight"] * row["rating"] for row in evidence) / weight_sum
        return {"preference_score": score, "support_count": len(evidence),
                "weight_sum": weight_sum, "neighbor_evidence": evidence}


def recommend(user, products, history=None, reference_users=None, top_k=3):
    """Recommend eligible products using learned interaction preferences.

    API inputs never silently receive fictional history. Missing reference users
    with nonempty history is an error because labels cannot be safely resolved.
    Empty history explicitly abstains. Rank ties use product ID. Each result is
    an individual alternative within the budget, not a suggested allocation.
    """
    validate_top_k(top_k)
    validate_catalog(products)
    history = [] if history is None else history
    reference_users = [] if reference_users is None else reference_users
    # Validate even if the target profile is incomplete: malformed datasets must
    # not become invisible merely because a different gate also fails.
    _validate_training_data(reference_users, products, history)
    result = {
        "module": "data_driven", "policy_version": POLICY_VERSION,
        "method": "data_driven_profile_neighbor_ratings",
        "model_version": MODEL_VERSION,
        "user_id": user.get("user_id") if isinstance(user, dict) else None,
        "status": "no_evidence",
        "recommendations": [], "excluded": [],
        "warnings": ["Preference scores are ratings on a 1..5 scale; they are not "
                     "suitability probabilities, expected returns, or confidence estimates."],
        "evidence": {"target_history_excluded": True, "minimum_support": MIN_SUPPORT,
                     "neighbor_limit": NEIGHBOR_LIMIT, "max_distance": MAX_DISTANCE},
    }
    errors = profile_errors(user)
    candidates = []
    for product in products:
        decision = evaluate_eligibility(user, product)
        result["warnings"].extend(decision["warnings"])
        if decision["eligible"]:
            candidates.append((product, decision))
        else:
            result["excluded"].append({"product_id": product["product_id"],
                                       "stage": "eligibility", "reasons": decision["reasons"]})
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    if errors:
        result["status"] = "needs_profile_completion"
        result["profile_errors"] = errors
        return result
    if not candidates:
        result["status"] = "no_eligible_products"
        return result

    model = NeighborRatingModel().fit(reference_users, products, history,
                                      target_user_id=user["user_id"])
    result["warnings"].extend(model.warnings)
    neighbors = model.neighbors(user)
    result["evidence"].update({
        "training_users": len(model.peers), "training_interactions": len(model.ratings),
        "selected_neighbor_ids": [row["user_id"] for row in neighbors],
        "fitted_numeric_features": list(model.ranges),
    })
    supported = []
    for product, decision in candidates:
        prediction = model.predict(product["product_id"], neighbors)
        score = prediction["preference_score"]
        if score is None:
            result["excluded"].append({
                "product_id": product["product_id"], "stage": "insufficient_evidence",
                "reasons": [f"Need {MIN_SUPPORT} distinct neighboring raters; "
                            f"found {prediction['support_count']}"],
                "support_count": prediction["support_count"],
            })
            continue
        # Keep full precision until after sorting, so display rounding cannot
        # create artificial ties. Evidence is retained for offline audit.
        supported.append({
            "product_id": product["product_id"], "name": product["name"],
            **prediction, "score_unit": "explicit_preference_rating_1_to_5",
            "effective_risk": decision["effective_risk"],
            "objective_match": user["objective"] in product["objectives"],
            "logic": "Passed factual eligibility; ranked by neighboring users' ratings.",
        })
    supported.sort(key=lambda item: (-item["preference_score"], item["product_id"]))
    selected = supported[:top_k]
    for row in selected:
        row["preference_score"] = round(row["preference_score"], 6)
        row["weight_sum"] = round(row["weight_sum"], 6)
        row["neighbor_evidence"] = [dict(
            item, distance=round(item["distance"], 6), weight=round(item["weight"], 6)
        ) for item in row["neighbor_evidence"]]
    result["recommendations"] = selected
    result["eligible_supported_count"] = len(supported)
    result["eligible_unselected_ids"] = [row["product_id"] for row in supported[top_k:]]
    if selected:
        result["status"] = "ok"
        if any(not row["objective_match"] for row in selected):
            result["warnings"].append(
                "Some selected alternatives do not match the stated objective. "
                "Preference evidence cannot override the risk or liquidity gates."
            )
    else:
        result["warnings"].append(
            "Insufficient interaction evidence: use an explicitly identified rule-based "
            "fallback or request more evidence; no ML score was invented."
        )
    return result


def evaluate_holdout(users, products, history):
    """Leave one whole user out; measure only supported, eligible held-out rows.

    Each fold refits the numeric ranges without that user's profile/history.
    This checks the prototype's mechanics on sparse data. On the default
    fictional sample, metrics cannot establish real-world usefulness or safety.
    No timestamps or outcomes are supplied, so this is not a temporal backtest.
    """
    validate_catalog(products)
    by_id = _validate_training_data(users, products, history)
    by_product = {product["product_id"]: product for product in products}
    absolute_errors = []
    eligible_rows = 0
    fold_count = 0
    for uid in sorted({row["user_id"] for row in history}):
        if profile_errors(by_id[uid]):
            continue
        fold_count += 1
        # recommend() excludes uid inside fit, including feature range fitting.
        result = recommend(by_id[uid], products, history, users, top_k=max(1, len(products)))
        predicted = {row["product_id"]: row["preference_score"]
                     for row in result["recommendations"]}
        for row in history:
            if row["user_id"] != uid:
                continue
            pid = row["product_id"]
            if not evaluate_eligibility(by_id[uid], by_product[pid])["eligible"]:
                continue
            eligible_rows += 1
            if pid in predicted:
                absolute_errors.append(abs(predicted[pid] - float(row["rating"])))
    count = len(absolute_errors)
    return {
        "protocol": "leave_one_user_out; eligibility gated; supported predictions only",
        "folds": fold_count, "input_rating_rows": len(history),
        "eligible_heldout_rows": eligible_rows, "predicted_heldout_rows": count,
        "prediction_coverage": round(count / eligible_rows, 6) if eligible_rows else None,
        "mean_absolute_error_rating_units": (
            round(sum(absolute_errors) / count, 6) if count else None
        ),
        "limitations": [
            "Coverage and MAE must be read together; abstained rows are not scored.",
            "Sparse, selected ratings do not represent all users or unseen products.",
            "Preference error does not measure suitability, financial benefit, or fairness.",
            "Default samples are fictional; these metrics are only a mechanics check.",
            "No chronological backtest is possible without interaction timestamps.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Normalized JSON with users/products/history")
    parser.add_argument("--user-id", default="U001")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--evaluate", action="store_true", help="Run a user-held-out diagnostic")
    args = parser.parse_args()
    try:
        if args.input:
            data = json.loads(args.input.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not all(
                    key in data for key in ("users", "products", "history")):
                raise ValueError("Input must be an object containing users, products, history")
            provenance = "caller-supplied normalized JSON; source validity not asserted"
        else:
            # Placeholder records are in matching_core.py and are clearly labeled.
            data = {"users": sample_users(), "products": sample_products(),
                    "history": sample_history()}
            provenance = "fictional demonstration data; not extracted from the workbook"
        validate_top_k(args.top_k)
        validate_catalog(data["products"])
        by_id = _validate_training_data(data["users"], data["products"], data["history"])
        if args.evaluate:
            result = evaluate_holdout(data["users"], data["products"], data["history"])
        else:
            if args.user_id not in by_id:
                raise ValueError("Unknown target user_id: " + args.user_id)
            result = recommend(by_id[args.user_id], data["products"], data["history"],
                               data["users"], args.top_k)
        print(json.dumps({"data_provenance": provenance, **result}, indent=2, allow_nan=False))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"Input error: {error}\n")


if __name__ == "__main__":
    main()
