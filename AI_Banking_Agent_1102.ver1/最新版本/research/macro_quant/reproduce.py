"""Deterministic synthetic fixture and chronological validation, standard library only.

Not a source-data collector or evidence of investment performance. The core uses
the saved JSON fixture; the generator makes its fictional nature explicit.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import platform
import random
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from quant_recommender import load_json, recommend, weighted_cvar

ROOT = Path(__file__).resolve().parent


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n", encoding="utf-8")


def make_demo(config: dict) -> dict:
    """Generate settled horizon payoffs directly, not fictional raw market prices."""
    rep = config["reproduction"]
    rng = random.Random(rep["seed"])
    as_of = datetime.fromisoformat(rep["as_of"])
    n, horizon = rep["demo_scenarios"], config["model_params"]["horizon_days"]
    regime = rep["demo_regime_id"]
    products = []
    for pid, name, risk, lockup, wait, entry, exit_fee in [
        ("SYN_A", "虚构稳健样本A", 1, 0, 1, 0.0, 0.0),
        ("SYN_B", "虚构短债样本B", 2, 0, 2, 0.0003, 0.0002),
        ("SYN_C", "虚构均衡样本C", 3, 0, 2, 0.0005, 0.0003),
        ("SYN_D", "虚构高风险样本D", 4, 0, 2, 0.001, 0.001),
        ("SYN_LOCKED", "虚构长锁定样本", 2, 60, 2, 0.0, 0.0),
        ("SYN_NEW", "虚构无历史样本", 1, 0, 1, 0.0, 0.0),
    ]:
        products.append(dict(product_id=pid, name=name, risk_level=risk,
                             min_investment_minor=10000, lockup_days=lockup,
                             redemption_days=wait, active=True, facts_verified=True,
                             currency="CNY", entry_cost_rate=entry, exit_cost_rate=exit_fee,
                             facts_as_of=(as_of-timedelta(hours=1)).isoformat(),
                             source_id="SYNTHETIC_PRODUCT_TERMS_V1"))

    def features(index: int, decision: datetime) -> dict:
        cycle = math.sin(index / 8.0)
        inflation = math.sin(index / 14.0)
        stress = (1.0 + math.cos(index / 11.0)) / 2.0
        # GDP is released once per three synthetic 30-day periods.
        values = {
            "gdp_yoy": 0.04 + 0.013 * math.sin((index-index % 3) / 8.0),
            "cpi_yoy": 0.015 + 0.012 * inflation,
            "policy_rate": 0.02 + 0.003 * math.sin(index / 18.0),
            "term_spread": 0.006 + 0.003 * math.cos(index / 15.0),
            "market_volatility": 0.14 + 0.08 * stress,
            "market_momentum": 0.025 * cycle + rng.uniform(-0.004, 0.004),
        }
        result = {}
        for key, value in values.items():
            age = 45 + 30 * (index % 3) if key == "gdp_yoy" else (30 if key == "cpi_yoy" else 1)
            observation = decision - timedelta(days=age)
            lag = timedelta(days=30 if key == "gdp_yoy" else 10) if key in ("gdp_yoy", "cpi_yoy") else timedelta(hours=20)
            result[key] = dict(value=value, observation_end=observation.isoformat(),
                               available_at=(observation+lag).isoformat(),
                               source_id="SYNTHETIC_"+key.upper(),
                               vintage_id=f"synthetic-v1-{key}-{index-index%3 if key == 'gdp_yoy' else index:04d}")
        return result

    history = []
    for index in range(n):
        decision = as_of - timedelta(days=1 + (n-index)*horizon)
        end = decision + timedelta(days=horizon)
        f = features(index, decision)
        cycle, inflation = math.sin(index/8.0), math.sin(index/14.0)
        stress = (1.0+math.cos(index/11.0))/2.0
        cash = 0.0012 + 0.0002 * math.sin(index/18.0)
        returns = {
            "SYN_A": 0.0020 + 0.0005*cycle + rng.gauss(0.0, 0.00035),
            "SYN_B": 0.0034 - 0.0015*inflation + rng.gauss(0.0, 0.0009) - (0.004 if index % 37 == 0 else 0),
            "SYN_C": 0.0040 + 0.0090*cycle - 0.0040*stress + rng.gauss(0.0, 0.008),
            "SYN_D": 0.0090 + 0.0250*cycle + rng.gauss(0.0, 0.02),
        }
        snapshots = copy.deepcopy(products)
        for product in snapshots:
            product["facts_as_of"] = (decision-timedelta(hours=1)).isoformat()
        terms = {p["product_id"]: {k: p[k] for k in ("lockup_days", "redemption_days")} for p in snapshots if p["product_id"] in returns}
        costs = {p["product_id"]: {k: p[k] for k in ("entry_cost_rate", "exit_cost_rate")} for p in snapshots if p["product_id"] in returns}
        history.append(dict(scenario_id=f"S{index:04d}", regime_id=regime,
                            decision_at=decision.isoformat(), label_end=end.isoformat(),
                            label_available_at=(end+timedelta(hours=6)).isoformat(),
                            features=f, cash_return=cash, product_returns=returns,
                            product_terms=terms, product_costs=costs,
                            universe=sorted(returns), source_id="SYNTHETIC_SETTLED_PAYOFF_V1",
                            product_snapshots=snapshots))
    return dict(schema_version=config["schema_version"], as_of=as_of.isoformat(),
                regime_id=regime, return_convention=config["data_policy"]["return_convention"],
                provenance=dict(data_kind="synthetic", dataset_id="synthetic-macro-20261024-v1",
                                point_in_time_verified=True, market_index_id="SYNTHETIC_FEATURES_NO_PRICE_PATH",
                                source_manifest=[{"source_id": "SYNTHETIC", "generator": "reproduce.py:make_demo",
                                                  "seed": rep["seed"], "real_market_data": False}]),
                profile=dict(risk_tolerance=3, risk_capacity=3, budget_minor=100000,
                             horizon_days=90, max_redemption_days=3),
                current_features=features(n, as_of), products=products, history=history)


def net_return(gross: float, product: dict) -> float:
    return (1.0+gross)*(1.0-product["exit_cost_rate"])/(1.0+product["entry_cost_rate"])-1.0


def evaluate_walk_forward(data: dict, config: dict) -> dict:
    """Each fold has its own info cutoff, fitted scalers and known product facts."""
    history = sorted(data["history"], key=lambda r: (datetime.fromisoformat(r["decision_at"]), r["scenario_id"]))
    count = config["reproduction"]["walk_forward_test_periods"]
    if len(history) <= count:
        raise ValueError("Need training history preceding validation periods")
    folds = []
    for i in range(len(history)-count, len(history)):
        observed = history[i]
        fold = copy.deepcopy(data)
        fold["as_of"] = observed["decision_at"]
        fold["regime_id"] = observed["regime_id"]
        fold["current_features"] = copy.deepcopy(observed["features"])
        fold["products"] = copy.deepcopy(observed["product_snapshots"])
        fold["history"] = copy.deepcopy(history[:i])
        fold["provenance"]["dataset_id"] += "-"+observed["scenario_id"]
        outcomes = {}
        for mode in ("conditional", "uniform"):
            cfg = copy.deepcopy(config)
            cfg["model_params"]["weight_mode"] = mode
            prediction = recommend(fold, cfg)
            chosen = prediction["ranking"][0]["product_id"] if prediction["ranking"] else "CASH"
            realized = observed["cash_return"]
            drag = 0.0
            if chosen != "CASH":
                product = next(p for p in fold["products"] if p["product_id"] == chosen)
                realized = net_return(observed["product_returns"][chosen], product)
                drag = observed["product_returns"][chosen]-realized
                if not (product["risk_level"] <= min(fold["profile"]["risk_tolerance"], fold["profile"]["risk_capacity"])
                        and product["min_investment_minor"] <= fold["profile"]["budget_minor"]
                        and product["lockup_days"]+product["redemption_days"] <= min(fold["profile"]["horizon_days"], cfg["model_params"]["horizon_days"])
                        and product["redemption_days"] <= fold["profile"]["max_redemption_days"]):
                    raise AssertionError("Suitability violation in walk-forward")
            outcomes[mode] = dict(status=prediction["status"], chosen=chosen, realized_return=realized,
                                  excess_return=realized-observed["cash_return"], fee_drag=drag,
                                  reason_codes=prediction["reason_codes"],
                                  training_ids=prediction["diagnostics"].get("scenario_ids", []))
        folds.append(dict(scenario_id=observed["scenario_id"], decision_at=observed["decision_at"],
                          label_end=observed["label_end"], cash_return=observed["cash_return"], outcomes=outcomes))

    summary = {}
    for mode in ("conditional", "uniform"):
        wealth, cash_wealth, peak, max_drawdown = 1.0, 1.0, 1.0, 0.0
        outcomes = [f["outcomes"][mode] for f in folds]
        for f, outcome in zip(folds, outcomes):
            wealth *= 1.0+outcome["realized_return"]
            cash_wealth *= 1.0+f["cash_return"]
            peak = max(peak, wealth)
            max_drawdown = max(max_drawdown, 1.0-wealth/peak)
        summary[mode] = dict(
            compound_return=wealth-1.0, cash_compound_return=cash_wealth-1.0,
            relative_wealth_excess=wealth/cash_wealth-1.0, max_drawdown=max_drawdown,
            mean_excess_return=math.fsum(x["excess_return"] for x in outcomes)/count,
            realized_excess_loss_cvar=weighted_cvar([-x["excess_return"] for x in outcomes], [1.0/count]*count, config["model_params"]["cvar_alpha"]),
            recommendation_coverage=sum(x["chosen"] != "CASH" for x in outcomes)/count,
            abstention_rate=sum(x["status"] == "abstain" for x in outcomes)/count,
            no_positive_score_rate=sum(x["status"] == "no_positive_score" for x in outcomes)/count,
            switch_rate=sum(outcomes[j]["chosen"] != outcomes[j-1]["chosen"] for j in range(1,count))/(count-1),
            mean_fee_drag=math.fsum(x["fee_drag"] for x in outcomes)/count,
            suitability_violations=0,
        )
    return dict(validation_kind="synthetic_plumbing_only", parameter_search_performed=False,
                economic_validation=False, periods=count, horizon_days=config["model_params"]["horizon_days"],
                selection_policy="top1_else_cash; full close and reopen each horizon; fees applied each period",
                profile_policy="frozen synthetic user constraints; normalized wealth diagnostic, not an account simulation",
                metrics_definitions={
                    "compound_return": "product(1+r_net)-1",
                    "relative_wealth_excess": "product(1+r_net)/product(1+cash)-1",
                    "max_drawdown": "max(1-wealth/running_peak), initial wealth=1 included",
                    "realized_excess_loss_cvar": "equal-period weighted CVaR of -(realized_net-cash); signed",
                    "switch_rate": "chosen product or CASH changes divided by periods-1; not dollar turnover",
                    "mean_fee_drag": "mean(gross_horizon_return-net_horizon_return); return drag including foregone earnings on entry fees, not actual fee cash/B",
                }, summaries=summary, folds=folds)


def check_existing_code() -> dict:
    manifest = json.loads((ROOT/"preserved_baseline.json").read_text(encoding="utf-8-sig"))
    base = ROOT.parents[1]
    mismatches = []
    for item in manifest["files"]:
        path = base/item["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            mismatches.append(item["path"])
    if mismatches:
        raise AssertionError(f"Pre-existing code changed: {mismatches}")
    return {"files_checked": len(manifest["files"]), "changed": mismatches}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regenerate", action="store_true", help="Regenerate synthetic fixture from the documented seed")
    args = parser.parse_args()
    config = load_json(ROOT/"params.json")
    input_path = ROOT/"example_input.json"
    if args.regenerate or not input_path.exists():
        write_json(input_path, make_demo(config))
    data = load_json(input_path)
    before = copy.deepcopy(data)
    first = recommend(data, config)
    second = recommend(data, config)
    assert first == second, "Non-deterministic result"
    assert data == before, "Input mutation"
    write_json(ROOT/"example_output.json", first)
    subprocess.run([sys.executable, str(ROOT/"quant_recommender.py"),
                    "--config", str(ROOT/"params.json"), "--input", str(input_path),
                    "--output", str(ROOT/"cli_output.json")], check=True, capture_output=True, text=True)
    assert (ROOT/"example_output.json").read_bytes() == (ROOT/"cli_output.json").read_bytes(), "CLI/function mismatch"
    validation = evaluate_walk_forward(data, config)
    write_json(ROOT/"walk_forward_report.json", validation)
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern="test_*.py")
    tests = unittest.TextTestRunner(verbosity=1).run(suite)
    if not tests.wasSuccessful():
        raise SystemExit(1)
    preserved = check_existing_code()
    files = ("params.json", "quant_recommender.py", "reproduce.py", "test_quant_recommender.py",
             "example_input.json", "example_output.json", "cli_output.json", "walk_forward_report.json",
             "项目目标与思路.md", "INTERFACE.md", "context.json", "preserved_baseline.json")
    hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files if (ROOT/name).exists()}
    report = dict(status="passed", python=platform.python_version(), model_version=config["model_version"],
                  test_count=tests.testsRun, test_failures=len(tests.failures), test_errors=len(tests.errors),
                  deterministic_repeat=True, input_unchanged=True, cli_matches_function=True, existing_code=preserved,
                  example_status=first["status"], walk_forward_periods=validation["periods"],
                  economic_validation=False, sha256=hashes)
    write_json(ROOT/"verification.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "sha256"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
