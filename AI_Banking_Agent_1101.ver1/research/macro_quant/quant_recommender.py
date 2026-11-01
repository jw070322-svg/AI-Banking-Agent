"""Conditional historical-scenario product ranking; Python standard library only.

See 项目目标与思路.md for the derivation and params.json for the contract.
This module is offline research. It neither authorizes nor executes trades.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "macro-quant-1.0"
RETURN_CONVENTION = "cash_settled_horizon_excluding_entry_exit_v1"


def _number(value, name: str, low=None, high=None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: finite number required (not bool)")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name}: number outside supported range") from exc
    if not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"{name}: number outside allowed finite range")
    return value


def _integer(value, name: str, low=0, high=None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError(f"{name}: integer in allowed range required")
    return value


def _string(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: nonempty string required")
    return value


def _boolean(value, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name}: bool required")
    return value


def _object(value, name: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError(f"{name}: object with string keys required")
    return value


def _array(value, name: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{name}: array required")
    return value


def _time(value, name: str) -> datetime:
    _string(value, name)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("missing timezone")
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name}: valid timezone-aware ISO8601 timestamp required") from exc


def _fee(value, name: str) -> float:
    result = _number(value, name, 0)
    if result >= 1:
        raise ValueError(f"{name}: fee must be less than 1")
    return result


def _canonical_hash(value) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Input/config must be finite JSON data") from exc
    return hashlib.sha256(raw).hexdigest()


def load_json(path) -> dict:
    """Reject ambiguous duplicate keys and non-standard JSON numeric constants."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")

    value = json.loads(Path(path).read_text(encoding="utf-8-sig"),
                       object_pairs_hook=pairs, parse_constant=constant)
    _object(value, "JSON root")
    _canonical_hash(value)  # Also catches overflowing JSON literals such as 1e999.
    return value


def _loss_distribution(losses, weights, alpha):
    alpha = _number(alpha, "alpha")
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie strictly between 0 and 1")
    if len(losses) == 0 or len(losses) != len(weights):
        raise ValueError("losses and weights must have equal nonzero lengths")
    values = [_number(v, "loss") for v in losses]
    probabilities = [_number(w, "weight", 0) for w in weights]
    total = math.fsum(probabilities)
    if not math.isfinite(total) or abs(total-1.0) > 1e-10:
        raise ValueError("weights must sum to one")
    return values, [w/total for w in probabilities], alpha


def weighted_cvar(losses: list[float], weights: list[float], alpha: float) -> float:
    """Exact discrete upper-tail CVaR, including a fractional boundary atom.

    Signed losses are intentional: CVaR can be negative. Probabilities must sum
    to one; only floating-point normalization error is corrected.
    """
    values, probabilities, alpha = _loss_distribution(losses, weights, alpha)
    tail = 1.0-alpha
    remaining = tail
    parts = []
    for loss, probability in sorted(zip(values, probabilities), key=lambda pair: pair[0], reverse=True):
        mass = min(probability, remaining)
        if mass > 0:
            parts.append((mass/tail)*loss)
            remaining -= mass
        if remaining <= 0:
            break
    value = math.fsum(parts)
    if not math.isfinite(value):
        raise ValueError("CVaR outside supported numerical range")
    return value


def weighted_var(losses, weights, alpha) -> float:
    """Left inverse of the discrete loss CDF: inf{x: F(x) >= alpha}."""
    values, probabilities, alpha = _loss_distribution(losses, weights, alpha)
    prefix = []
    ordered = sorted(zip(values, probabilities))
    for value, probability in ordered:
        prefix.append(probability)
        if math.fsum(prefix) >= alpha:
            return value
    return ordered[-1][0]


def _config(config: dict):
    _object(config, "config")
    if config.get("schema_version") != SCHEMA:
        raise ValueError("config schema_version mismatch")
    _string(config.get("model_version"), "model_version")
    p = dict(_object(config.get("model_params"), "model_params"))
    for key, low in (("horizon_days", 1), ("lookback_days", 1), ("min_samples", 2), ("top_k", 1)):
        _integer(p.get(key), key, low)
    for key in ("bandwidth", "half_life_days", "min_tail_ess", "max_nearest_distance", "scale_epsilon", "comparison_tolerance"):
        p[key] = _number(p.get(key), key)
        if p[key] <= 0:
            raise ValueError(f"{key}: must be positive")
    p["min_kernel_ess"] = _number(p.get("min_kernel_ess"), "min_kernel_ess", 1)
    p["min_score"] = _number(p.get("min_score"), "min_score", 0)
    p["risk_aversion"] = _number(p.get("risk_aversion"), "risk_aversion", 0, 1)
    p["uniform_mixture"] = _number(p.get("uniform_mixture"), "uniform_mixture", 0)
    if p["uniform_mixture"] >= 1:
        raise ValueError("uniform_mixture must be less than one")
    p["cvar_alpha"] = _number(p.get("cvar_alpha"), "cvar_alpha")
    if not 0 < p["cvar_alpha"] < 1:
        raise ValueError("cvar_alpha must be between zero and one")
    if p.get("weight_mode") not in ("conditional", "uniform"):
        raise ValueError("weight_mode must be conditional or uniform")
    # A large comparison tolerance must not silently disable support checks.
    if p["comparison_tolerance"] > 1e-6:
        raise ValueError("comparison_tolerance must not exceed 1e-6")
    features = _object(config.get("feature_definitions"), "feature_definitions")
    if not features:
        raise ValueError("feature_definitions cannot be empty")
    for key, definition in features.items():
        _string(key, "feature id")
        _object(definition, key)
        if _number(definition.get("weight"), key+".weight") <= 0:
            raise ValueError("feature weights must be positive")
        _integer(definition.get("max_age_days"), key+".max_age_days", 1)
    return p, features


def _observations(values, keys, cutoff, definitions, path):
    """Malformed fields raise; missing or temporally invalid observations abstain."""
    values = _object(values, path)
    result, reasons = {}, []
    for key in keys:
        if key not in values:
            reasons.append(f"missing_feature:{key}")
            continue
        row = _object(values[key], path+"."+key)
        result[key] = _number(row.get("value"), path+"."+key+".value")
        observation = _time(row.get("observation_end"), "observation_end")
        available = _time(row.get("available_at"), "available_at")
        _string(row.get("source_id"), "source_id")
        _string(row.get("vintage_id"), "vintage_id")
        if observation > available:
            reasons.append(f"observation_after_availability:{key}")
        if available > cutoff or observation > cutoff:
            reasons.append(f"future_feature:{key}")
        if (cutoff-observation).total_seconds()/86400 > definitions[key]["max_age_days"]:
            reasons.append(f"stale_feature:{key}")
        if key == "market_volatility" and result[key] < 0:
            raise ValueError("market_volatility must be nonnegative")
        if key == "market_momentum" and result[key] < -1:
            raise ValueError("market_momentum must be at least -1")
    return result, reasons


def _product(product, as_of):
    _object(product, "product")
    pid = _string(product.get("product_id"), "product_id")
    _string(product.get("name"), "name")
    _integer(product.get("risk_level"), "risk_level", 1, 5)
    for key in ("min_investment_minor", "lockup_days", "redemption_days"):
        _integer(product.get(key), key)
    _boolean(product.get("active"), "active")
    _boolean(product.get("facts_verified"), "facts_verified")
    _string(product.get("currency"), "currency")
    _fee(product.get("entry_cost_rate"), "entry_cost_rate")
    _fee(product.get("exit_cost_rate"), "exit_cost_rate")
    _string(product.get("source_id"), "source_id")
    return pid, _time(product.get("facts_as_of"), "facts_as_of") > as_of


def _history(data, keys, definitions, p, as_of, regime):
    retained, rejected, ids = [], [], set()
    for raw in _array(data.get("history"), "history"):
        _object(raw, "scenario")
        sid = _string(raw.get("scenario_id"), "scenario_id")
        if sid in ids:
            raise ValueError("duplicate scenario_id: "+sid)
        ids.add(sid)
        start = _time(raw.get("decision_at"), "decision_at")
        end = _time(raw.get("label_end"), "label_end")
        available = _time(raw.get("label_available_at"), "label_available_at")
        _string(raw.get("source_id"), "scenario.source_id")
        row_regime = _string(raw.get("regime_id"), "scenario.regime_id")
        vector, reasons = _observations(raw.get("features"), keys, start, definitions, "history.features")
        cash = _number(raw.get("cash_return"), "cash_return")
        if cash <= -1:
            raise ValueError("cash_return must exceed -1")
        returns = _object(raw.get("product_returns"), "product_returns")
        for pid, value in returns.items():
            _string(pid, "historical product_id")
            _number(value, "product_returns."+pid, -1)
        terms = _object(raw.get("product_terms"), "product_terms")
        for term in terms.values():
            _object(term, "historical terms")
            _integer(term.get("lockup_days"), "historical lockup_days")
            _integer(term.get("redemption_days"), "historical redemption_days")
        if "product_costs" in raw:
            for costs in _object(raw["product_costs"], "product_costs").values():
                _object(costs, "historical costs")
                _fee(costs.get("entry_cost_rate"), "historical entry_cost_rate")
                _fee(costs.get("exit_cost_rate"), "historical exit_cost_rate")
        universe = _array(raw.get("universe"), "universe")
        for pid in universe:
            _string(pid, "universe product_id")
        if len(set(universe)) != len(universe):
            raise ValueError("duplicate universe product_id")
        age = (as_of-start).total_seconds()/86400
        if start >= as_of:
            reasons.append("future_decision")
        if end > as_of or available > as_of:
            reasons.append("label_not_available")
        if end < start or available < end:
            reasons.append("invalid_label_time_order")
        if (end-start).total_seconds() != p["horizon_days"]*86400:
            reasons.append("horizon_mismatch")
        if age > p["lookback_days"]:
            reasons.append("outside_lookback")
        if row_regime != regime:
            reasons.append("regime_mismatch")
        if reasons:
            rejected.append({"scenario_id": sid, "reasons": reasons})
        else:
            retained.append(dict(raw=raw, scenario_id=sid, start=start, end=end,
                                 age=age, vector=vector, cash=cash))
    retained.sort(key=lambda row: (row["start"], row["scenario_id"]))
    rejected.sort(key=lambda row: row["scenario_id"])
    return retained, rejected


def recommend(data: dict, config: dict) -> dict:
    """Return a deterministic, auditable ranking or a normal abstention result."""
    p, definitions = _config(config)
    keys = sorted(definitions)
    _object(data, "data")
    if data.get("schema_version") != SCHEMA:
        raise ValueError("input schema_version mismatch")
    if data.get("return_convention") != RETURN_CONVENTION:
        raise ValueError("unsupported return_convention")
    as_of = _time(data.get("as_of"), "as_of")
    regime = _string(data.get("regime_id"), "regime_id")
    provenance = _object(data.get("provenance"), "provenance")
    if provenance.get("data_kind") not in ("synthetic", "observed"):
        raise ValueError("data_kind must be synthetic or observed")
    _string(provenance.get("dataset_id"), "dataset_id")
    verified = _boolean(provenance.get("point_in_time_verified"), "point_in_time_verified")
    profile = _object(data.get("profile"), "profile")
    for key in ("risk_tolerance", "risk_capacity"):
        _integer(profile.get(key), key, 1, 5)
    _integer(profile.get("budget_minor"), "budget_minor")
    _integer(profile.get("horizon_days"), "profile.horizon_days", 1)
    _integer(profile.get("max_redemption_days"), "max_redemption_days")
    products = _array(data.get("products"), "products")
    seen, future_facts = set(), {}
    for product in products:
        pid, future = _product(product, as_of)
        if pid in seen:
            raise ValueError("duplicate product_id: "+pid)
        seen.add(pid)
        future_facts[pid] = future
    current, current_reasons = _observations(data.get("current_features"), keys, as_of, definitions, "current_features")
    rows, rejected = _history(data, keys, definitions, p, as_of, regime)
    diagnostics = {"scenario_ids": [r["scenario_id"] for r in rows], "rejected_history": rejected,
                   "scenario_count": len(rows), "weight_mode": p["weight_mode"]}
    warnings = ["illustrative_parameters_not_calibrated", "ess_is_weight_concentration_not_independent_sample_size",
                "source_authenticity_requires_upstream_evidence", "current_fee_counterfactual_scenarios"]
    if provenance["data_kind"] == "synthetic":
        warnings.append("synthetic_data_no_economic_validation")
    result = dict(schema_version=SCHEMA, model_version=config["model_version"], as_of=data["as_of"],
                  data_kind=provenance["data_kind"], dataset_id=provenance["dataset_id"],
                  research_only=True, ledger_modified=False, input_sha256=_canonical_hash(data),
                  config_sha256=_canonical_hash(config), status="abstain", reason_codes=[],
                  ranking=[], evaluated=[], excluded=[], diagnostics=diagnostics, warnings=warnings)

    def abstain(*reasons):
        result["reason_codes"] = list(reasons)
        return result

    if not verified:
        return abstain("unverified_point_in_time")
    if current_reasons:
        return abstain(*current_reasons)
    if any(rows[i]["start"] < rows[i-1]["end"] for i in range(1, len(rows))):
        return abstain("overlapping_horizons")
    n = len(rows)
    if n < p["min_samples"]:
        return abstain("insufficient_samples")

    scalers, active, constant, shifted = {}, [], [], []
    for key in keys:
        values = [r["vector"][key] for r in rows]
        mean = math.fsum(v/n for v in values)
        # hypot avoids overflow in the sum of squares for finite scaled inputs.
        std = math.hypot(*(v-mean for v in values))/math.sqrt(n)
        if not math.isfinite(mean) or not math.isfinite(std):
            raise ValueError("Feature scale outside supported numerical range")
        scalers[key] = {"mean": mean, "std": std}
        if std <= p["scale_epsilon"]:
            constant.append(key)
            if abs(current[key]-mean) > p["scale_epsilon"]:
                shifted.append(key)
        else:
            active.append(key)
    diagnostics.update(scalers=scalers, active_features=active, constant_features=constant)
    if shifted:
        diagnostics["shifted_constant_features"] = shifted
        return abstain("constant_feature_shift")
    if not active:
        return abstain("all_features_constant")
    # Renormalize surviving feature weights without overflowing their sum.
    largest_weight = max(definitions[key]["weight"] for key in active)
    scaled_weights = {key: definitions[key]["weight"]/largest_weight for key in active}
    total_weight = math.fsum(scaled_weights.values())
    a = {key: scaled_weights[key]/total_weight for key in active}
    distances = [math.hypot(*(math.sqrt(a[key]) * ((r["vector"][key]-current[key])/scalers[key]["std"])
                             for key in active)) for r in rows]
    if not all(math.isfinite(d) for d in distances):
        raise ValueError("Feature distance outside supported numerical range")
    nearest = min(distances)
    diagnostics.update(feature_weights=a, nearest_distance=nearest)
    if nearest > p["max_nearest_distance"]:
        return abstain("current_state_out_of_support")
    try:
        logs = [-0.5*(d/p["bandwidth"])**2-math.log(2)*r["age"]/p["half_life_days"] for d, r in zip(distances, rows)]
    except OverflowError as exc:
        raise ValueError("Kernel parameters outside supported numerical range") from exc
    if not any(math.isfinite(v) for v in logs):
        raise ValueError("All kernel weights underflowed in log space")
    maximum = max(logs)
    exp_weights = [math.exp(v-maximum) for v in logs]
    total = math.fsum(exp_weights)
    q = [v/total for v in exp_weights]
    rho = p["uniform_mixture"]
    mixed = [(1-rho)*v+rho/n for v in q]
    probabilities = [1/n]*n if p["weight_mode"] == "uniform" else mixed
    ess_q = 1/math.fsum(v*v for v in q)
    ess_mixed = 1/math.fsum(v*v for v in mixed)
    diagnostics.update(kernel_ess=ess_q, mixed_ess=ess_mixed,
                       kernel_tail_support=(1-p["cvar_alpha"])*ess_q,
                       mixed_tail_support=(1-p["cvar_alpha"])*ess_mixed,
                       applied_ess=1/math.fsum(v*v for v in probabilities),
                       weights=[dict(scenario_id=r["scenario_id"], distance=d, kernel_weight=qi, weight=pi)
                                for r, d, qi, pi in zip(rows, distances, q, probabilities)])
    tol = p["comparison_tolerance"]
    support_reasons = []
    if ess_q+tol < p["min_kernel_ess"]:
        support_reasons.append("insufficient_kernel_ess")
    if diagnostics["kernel_tail_support"]+tol < p["min_tail_ess"]:
        support_reasons.append("insufficient_tail_support")
    if support_reasons:
        return abstain(*support_reasons)

    for product in sorted(products, key=lambda item: item["product_id"]):
        pid, reasons = product["product_id"], []
        if not product["active"]:
            reasons.append("inactive")
        if not product["facts_verified"]:
            reasons.append("unverified_facts")
        if future_facts[pid]:
            reasons.append("future_product_facts")
        if product["currency"] != "CNY":
            reasons.append("unsupported_currency")
        if product["risk_level"] > min(profile["risk_tolerance"], profile["risk_capacity"]):
            reasons.append("risk_limit")
        if profile["budget_minor"] <= 0 or product["min_investment_minor"] > profile["budget_minor"]:
            reasons.append("budget_limit")
        if product["lockup_days"]+product["redemption_days"] > min(profile["horizon_days"], p["horizon_days"]):
            reasons.append("holding_horizon_limit")
        if product["redemption_days"] > profile["max_redemption_days"]:
            reasons.append("redemption_limit")
        if not reasons:
            if any(pid not in row["raw"]["product_returns"] for row in rows):
                reasons.append("missing_common_returns")
            if any(pid not in row["raw"]["universe"] for row in rows):
                reasons.append("not_in_historical_universe")
            if any(pid not in row["raw"]["product_terms"] or
                   any(row["raw"]["product_terms"][pid][k] != product[k] for k in ("lockup_days", "redemption_days"))
                   for row in rows):
                reasons.append("return_terms_mismatch")
        if reasons:
            result["excluded"].append({"product_id": pid, "reasons": reasons})
            continue
        net = [(1+row["raw"]["product_returns"][pid])*(1-product["exit_cost_rate"])/(1+product["entry_cost_rate"])-1 for row in rows]
        excess = [value-row["cash"] for value, row in zip(net, rows)]
        if not all(math.isfinite(v) for v in excess+net):
            raise ValueError("Return arithmetic outside supported numerical range")
        mean = math.fsum(w*v for w, v in zip(probabilities, excess))
        mean_net = math.fsum(w*v for w, v in zip(probabilities, net))
        volatility = math.hypot(*(math.sqrt(w)*(v-mean) for w, v in zip(probabilities, excess)))
        losses = [-v for v in excess]
        cvar = weighted_cvar(losses, probabilities, p["cvar_alpha"])
        score = (1-p["risk_aversion"])*mean-p["risk_aversion"]*cvar
        if not all(math.isfinite(v) for v in (mean, mean_net, volatility, score)):
            raise ValueError("Score outside supported numerical range")
        result["evaluated"].append(dict(product_id=pid, name=product["name"], mean_net_return=mean_net,
                                         mean_excess_return=mean, volatility=volatility,
                                         loss_var=weighted_var(losses, probabilities, p["cvar_alpha"]),
                                         loss_cvar=cvar, score=score, scenario_count=n))
    result["evaluated"].sort(key=lambda item: (-item["score"], item["product_id"]))
    result["ranking"] = [dict(item) for item in result["evaluated"] if item["score"] > p["min_score"]+tol][:p["top_k"]]
    result["status"] = "ok" if result["ranking"] else "no_positive_score"
    if not result["evaluated"]:
        result["reason_codes"] = ["no_eligible_products"]
    elif not result["ranking"]:
        result["reason_codes"] = ["no_score_above_cash_threshold"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = recommend(load_json(args.input), load_json(args.config))
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                               indent=2, allow_nan=False)+"\n", encoding="utf-8")
    except (ValueError, OSError, OverflowError) as exc:
        parser.exit(2, f"Invalid request: {exc}\n")
    print(json.dumps({"status": result["status"], "ranked_products": len(result["ranking"]),
                      "output": str(Path(args.output))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
