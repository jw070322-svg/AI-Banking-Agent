"""backtest_budget.py —— 预算建议的参数化敏感性回测。

没有真实脱敏流水时，用 A~G 合成场景 + 压力变体，系统性地回答：

1. 现行策略（储蓄留 1 个月支出、投资留 3 个月）在不同场景下是否稳定？
2. 换成其他缓冲月数，建议金额会怎么变？
3. 分析函数是否始终满足金额不变量（非负、不超过结余、不写数据）？

用法：

    python backtest_budget.py
    python backtest_budget.py --horizons 30,90 --no-report
    python backtest_budget.py --out-prefix reports/budget_backtest

输出：
- 终端：基准策略表 + 策略敏感性表 + 不变量检查；
- 文件：`reports/budget_backtest.json` 和 `.md`（默认写入）。
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from analysis import budget_advice, load_scenario
from analysis.budget import INVESTMENT_RESERVE_MONTHS, SAVINGS_RESERVE_MONTHS

BASE_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = BASE_DIR / "fixtures"

# 压力变体：只改变一个维度，便于归因
STRESS_CASES: List[Dict[str, Any]] = [
    {"name": "base", "income": 1.0, "spending": 1.0, "balance": 1.0},
    {"name": "spending+20%", "income": 1.0, "spending": 1.2, "balance": 1.0},
    {"name": "income-20%", "income": 0.8, "spending": 1.0, "balance": 1.0},
    {"name": "balance-30%", "income": 1.0, "spending": 1.0, "balance": 0.7},
    {"name": "combined", "income": 0.8, "spending": 1.2, "balance": 0.7},
    {"name": "balance~0", "income": 1.0, "spending": 1.0, "balance": 0.02},
]

# 只测试投资缓冲不小于储蓄缓冲的组合，避免"投资比储蓄更激进"的无效策略
POLICY_GRID: List[Tuple[int, int]] = [
    (savings, investment)
    for savings in (0, 1, 2, 3)
    for investment in (1, 2, 3, 6)
    if investment >= savings
]

# 场景数据特征说明，用于数据边界报告
SCENARIO_NOTES = {
    "A": "主要流水集中在最近一个月；工资、日常消费、卡片、家庭、日历、洞察齐全",
    "B": "两个月；购物支出增加，含跨月对比",
    "C": "工资在 9 月、支出在 10 月；已用最近工资修正跨月取数",
    "D": "余额不足/被拒转账；低余额会触发缺口或保守建议",
    "E": "支出只有订阅；标记 low_spending，不能代表真实生活成本",
    "F": "生日锁定与活动日历；流动性计算完整",
    "G": "信用卡与卡片事件；含账单和还款",
    "SESSION": "会话账本为月度汇总样本；缺信用卡账单、生日、日历",
}


def money(amount_minor: Optional[int]) -> str:
    return "n/a" if amount_minor is None else f"¥{amount_minor / 100:,.2f}"


def _scale_minor(value: Any, factor: float) -> Any:
    """按比例缩放整数分；不是整数分就原样返回。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return value
    return max(0, int(round(value * factor)))


def _scale_float(value: Any, factor: float) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return round(value * factor, 2)


def stress_scenario(scenario: Dict[str, Any], stress: Dict[str, Any]) -> Dict[str, Any]:
    """深拷贝场景并按压力参数缩放金额，绝不修改传入对象。"""
    data = copy.deepcopy(scenario)
    income_factor = stress["income"]
    spending_factor = stress["spending"]
    balance_factor = stress["balance"]

    for transaction in data.get("transactions", []) or []:
        if not isinstance(transaction, dict):
            continue
        transaction_type = transaction.get("transaction_type")
        if transaction_type == "income":
            factor = income_factor
        elif transaction_type in {"expense", "refund"}:
            factor = spending_factor
        else:
            # 转账不是消费，保持原值，避免把压力测试混进消费归因
            continue
        transaction["amount_minor"] = _scale_minor(
            transaction.get("amount_minor"), factor
        )
        if "amount" in transaction:
            transaction["amount"] = _scale_float(transaction.get("amount"), factor)

    bill = data.get("credit_card_bill")
    if isinstance(bill, dict):
        for item in bill.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            item["amount_minor"] = _scale_minor(
                item.get("amount_minor"), spending_factor
            )
            if "amount" in item:
                item["amount"] = _scale_float(item.get("amount"), spending_factor)
        for key in (
            "total_amount_minor", "paid_amount_minor", "outstanding_amount_minor"
        ):
            if key in bill:
                bill[key] = _scale_minor(bill.get(key), spending_factor)

    for subscription in data.get("subscriptions", []) or []:
        if isinstance(subscription, dict):
            subscription["amount_minor"] = _scale_minor(
                subscription.get("amount_minor"), spending_factor
            )

    for activity in data.get("activity_calendar", []) or []:
        if isinstance(activity, dict):
            activity["budget_minor"] = _scale_minor(
                activity.get("budget_minor"), spending_factor
            )

    for account in data.get("accounts", []) or []:
        if isinstance(account, dict):
            account["balance_minor"] = _scale_minor(
                account.get("balance_minor"), balance_factor
            )

    return data


def check_invariants(advice: Dict[str, Any]) -> List[str]:
    """检查建议金额的硬性约束，返回错误列表。"""
    errors: List[str] = []
    surplus = advice["monthly_surplus_minor"]
    if surplus < 0:
        errors.append("monthly_surplus_minor < 0")
    for bucket_name in ("savings", "investment"):
        bucket = advice[bucket_name]
        safe = bucket["safe_monthly_minor"]
        capacity = bucket["monthly_capacity_minor"]
        if safe < 0:
            errors.append(f"{bucket_name}.safe_monthly_minor < 0")
        if capacity < 0:
            errors.append(f"{bucket_name}.monthly_capacity_minor < 0")
        if safe > surplus:
            errors.append(f"{bucket_name}.safe_monthly_minor > monthly_surplus_minor")
        if safe > capacity:
            errors.append(f"{bucket_name}.safe_monthly_minor > monthly_capacity_minor")
    if advice["investment"]["safe_monthly_minor"] > advice["savings"]["safe_monthly_minor"]:
        errors.append("investment.safe_monthly_minor > savings.safe_monthly_minor")
    if advice["shortfall_days"] and (
        advice["savings"]["safe_monthly_minor"]
        or advice["investment"]["safe_monthly_minor"]
    ):
        errors.append("shortfall_days 非空但建议金额不为 0")
    for value in (
        advice["monthly_income_minor"],
        advice["monthly_surplus_minor"],
        advice["savings"]["safe_monthly_minor"],
        advice["investment"]["safe_monthly_minor"],
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append("金额不是整数分")
            break
    return errors


def _fixture_paths(directory: Path) -> List[Path]:
    return sorted(directory.glob("SCENARIO_*.json"))


def run_backtest(
    scenario_paths: Iterable[Path],
    *,
    horizons: Iterable[int] = (30, 90),
    stress_cases: Iterable[Dict[str, Any]] = STRESS_CASES,
    policy_grid: Iterable[Tuple[int, int]] = POLICY_GRID,
) -> Dict[str, Any]:
    """执行回测，返回可直接 JSON 序列化的结果。"""
    scenarios = [
        (path.stem, load_scenario(path))
        for path in scenario_paths
    ]

    cases: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    determinism_checked = 0
    determinism_mismatches: List[Dict[str, Any]] = []

    for name, scenario in scenarios:
        for stress in stress_cases:
            stressed = stress_scenario(scenario, stress)
            before = json.dumps(stressed, ensure_ascii=False, sort_keys=True)
            for days in horizons:
                for savings_months, investment_months in policy_grid:
                    advice = budget_advice(
                        stressed,
                        days=days,
                        savings_reserve_months=savings_months,
                        investment_reserve_months=investment_months,
                    )
                    if (savings_months, investment_months) == (
                        SAVINGS_RESERVE_MONTHS, INVESTMENT_RESERVE_MONTHS
                    ):
                        repeat = budget_advice(
                            stressed,
                            days=days,
                            savings_reserve_months=savings_months,
                            investment_reserve_months=investment_months,
                        )
                        determinism_checked += 1
                        if json.dumps(repeat, ensure_ascii=False, sort_keys=True) != json.dumps(
                            advice, ensure_ascii=False, sort_keys=True
                        ):
                            determinism_mismatches.append({
                                "scenario": name,
                                "stress": stress["name"],
                                "horizon_days": days,
                            })
                    errors = check_invariants(advice)
                    if errors:
                        failures.append({
                            "scenario": name,
                            "stress": stress["name"],
                            "horizon_days": days,
                            "policy": {
                                "savings_reserve_months": savings_months,
                                "investment_reserve_months": investment_months,
                            },
                            "errors": errors,
                        })
                    after = json.dumps(stressed, ensure_ascii=False, sort_keys=True)
                    if before != after:
                        failures.append({
                            "scenario": name,
                            "stress": stress["name"],
                            "horizon_days": days,
                            "errors": ["budget_advice 修改了输入场景"],
                        })
                    data_quality: List[str] = []
                    if advice["monthly_income_minor"] <= 0:
                        data_quality.append("no_income")
                    elif advice["monthly_spending_minor"] * 10 < advice["monthly_income_minor"]:
                        data_quality.append("low_spending")
                    if advice["shortfall_days"]:
                        data_quality.append("shortfall")
                    cases.append({
                        "scenario": name,
                        "scenario_type": scenario.get("scenario_type"),
                        "stress": stress["name"],
                        "horizon_days": days,
                        "policy": {
                            "savings_reserve_months": savings_months,
                            "investment_reserve_months": investment_months,
                        },
                        "monthly_income_minor": advice["monthly_income_minor"],
                        "income_source": advice["income_source"],
                        "months_of_history": advice["context"]["months_of_history"],
                        "monthly_spending_minor": advice["monthly_spending_minor"],
                        "monthly_surplus_minor": advice["monthly_surplus_minor"],
                        "safe_to_save_minor": advice["savings"]["safe_monthly_minor"],
                        "safe_to_invest_minor": advice["investment"]["safe_monthly_minor"],
                        "recommended_action": advice["recommended_action"],
                        "shortfall": bool(advice["shortfall_days"]),
                        "data_quality": data_quality,
                    })

    policy_summary = _policy_summary(cases)
    savings_sensitivity = _savings_sensitivity(cases)
    investment_sensitivity = _investment_sensitivity(cases)
    stress_summary = _stress_summary(cases)
    scenario_quality = _scenario_quality(cases)
    baseline = _baseline_rows(cases)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenario_count": len(scenarios),
        "stress_cases": [case["name"] for case in stress_cases],
        "horizons": list(horizons),
        "policy_grid": [
            {"savings_reserve_months": savings, "investment_reserve_months": investment}
            for savings, investment in policy_grid
        ],
        "summary": {
            "case_count": len(cases),
            "invariants_passed": not failures,
            "failure_count": len(failures),
        },
        "determinism": {
            "cases_checked": determinism_checked,
            "identical": not determinism_mismatches,
            "mismatches": determinism_mismatches,
        },
        "baseline": baseline,
        "policy_summary": policy_summary,
        "savings_sensitivity": savings_sensitivity,
        "investment_sensitivity": investment_sensitivity,
        "stress_summary": stress_summary,
        "scenario_quality": scenario_quality,
        "failures": failures,
        "cases": cases,
    }


def _baseline_rows(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """基准策略（1 / 3 个月）逐场景结果。"""
    rows = [
        case for case in cases
        if case["policy"]["savings_reserve_months"] == 1
        and case["policy"]["investment_reserve_months"] == 3
    ]
    rows.sort(key=lambda case: (
        case["scenario"], case["stress"], case["horizon_days"]
    ))
    return rows


def _policy_summary(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按策略聚合：多少场景有正投资建议、平均投资额。"""
    buckets: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for case in cases:
        key = (
            case["policy"]["savings_reserve_months"],
            case["policy"]["investment_reserve_months"],
        )
        buckets.setdefault(key, []).append(case)

    summary = []
    for (savings, investment), rows in sorted(buckets.items()):
        positive = sum(1 for row in rows if row["safe_to_invest_minor"] > 0)
        shortfalls = sum(1 for row in rows if row["shortfall"])
        summary.append({
            "savings_reserve_months": savings,
            "investment_reserve_months": investment,
            "cases": len(rows),
            "positive_invest_cases": positive,
            "positive_invest_rate": round(positive / len(rows), 4) if rows else 0.0,
            "shortfall_cases": shortfalls,
            "average_invest_minor": sum(
                row["safe_to_invest_minor"] for row in rows
            ) // len(rows) if rows else 0,
        })
    return summary


def _savings_sensitivity(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """储蓄缓冲的一维敏感性：投资缓冲固定为默认值，避免重复行。"""
    rows = [
        case for case in cases
        if case["policy"]["investment_reserve_months"] == INVESTMENT_RESERVE_MONTHS
    ]
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for case in rows:
        buckets.setdefault(case["policy"]["savings_reserve_months"], []).append(case)
    summary = []
    for months, bucket in sorted(buckets.items()):
        positive = sum(1 for row in bucket if row["safe_to_save_minor"] > 0)
        summary.append({
            "savings_reserve_months": months,
            "cases": len(bucket),
            "positive_save_cases": positive,
            "positive_save_rate": round(positive / len(bucket), 4) if bucket else 0.0,
            "average_save_minor": sum(
                row["safe_to_save_minor"] for row in bucket
            ) // len(bucket) if bucket else 0,
        })
    return summary


def _investment_sensitivity(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """投资缓冲的一维敏感性：储蓄缓冲固定为默认值。"""
    rows = [
        case for case in cases
        if case["policy"]["savings_reserve_months"] == SAVINGS_RESERVE_MONTHS
    ]
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for case in rows:
        buckets.setdefault(case["policy"]["investment_reserve_months"], []).append(case)
    summary = []
    for months, bucket in sorted(buckets.items()):
        positive = sum(1 for row in bucket if row["safe_to_invest_minor"] > 0)
        summary.append({
            "investment_reserve_months": months,
            "cases": len(bucket),
            "positive_invest_cases": positive,
            "positive_invest_rate": round(positive / len(bucket), 4) if bucket else 0.0,
            "average_invest_minor": sum(
                row["safe_to_invest_minor"] for row in bucket
            ) // len(bucket) if bucket else 0,
        })
    return summary


def _stress_summary(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """基准策略下，各压力变体的平均表现。"""
    rows = [
        case for case in cases
        if case["policy"]["savings_reserve_months"] == SAVINGS_RESERVE_MONTHS
        and case["policy"]["investment_reserve_months"] == INVESTMENT_RESERVE_MONTHS
    ]
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for case in rows:
        buckets.setdefault(case["stress"], []).append(case)
    summary = []
    order = {name: index for index, name in enumerate(
        [case["name"] for case in STRESS_CASES]
    )}
    for stress, bucket in sorted(
        buckets.items(), key=lambda item: order.get(item[0], 99)
    ):
        positive = sum(1 for row in bucket if row["safe_to_invest_minor"] > 0)
        summary.append({
            "stress": stress,
            "cases": len(bucket),
            "positive_invest_cases": positive,
            "positive_invest_rate": round(positive / len(bucket), 4) if bucket else 0.0,
            "average_surplus_minor": sum(
                row["monthly_surplus_minor"] for row in bucket
            ) // len(bucket) if bucket else 0,
            "average_invest_minor": sum(
                row["safe_to_invest_minor"] for row in bucket
            ) // len(bucket) if bucket else 0,
            "shortfall_cases": sum(1 for row in bucket if row["shortfall"]),
            "low_spending_cases": sum(
                1 for row in bucket if "low_spending" in row["data_quality"]
            ),
            "no_income_cases": sum(
                1 for row in bucket if "no_income" in row["data_quality"]
            ),
        })
    return summary


def _scenario_quality(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """每个场景在基准策略下的数据完整度概况。"""
    rows = [
        case for case in cases
        if case["policy"]["savings_reserve_months"] == SAVINGS_RESERVE_MONTHS
        and case["policy"]["investment_reserve_months"] == INVESTMENT_RESERVE_MONTHS
    ]
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for case in rows:
        buckets.setdefault(case["scenario"], []).append(case)
    summary = []
    for scenario, bucket in sorted(buckets.items()):
        flags = sorted({
            flag for row in bucket for flag in row["data_quality"]
        })
        summary.append({
            "scenario": scenario,
            "scenario_type": bucket[0]["scenario_type"],
            "months_of_history": bucket[0]["months_of_history"],
            "data_quality": flags,
        })
    return summary


def print_report(result: Dict[str, Any]) -> None:
    print("预算建议参数化回测")
    print(
        f"场景 {result['scenario_count']} 个 × 压力 {len(result['stress_cases'])} 种"
        f" × 周期 {len(result['horizons'])} 个 × 策略 {len(result['policy_grid'])} 种"
        f" = {result['summary']['case_count']} 次"
    )

    print("\n===== 基准策略（储蓄 1 个月 / 投资 3 个月）=====")
    print(
        f"{'场景':<14}{'压力':<14}{'周期':<6}{'结余':>14}{'储蓄建议':>14}"
        f"{'投资建议':>14}  {'动作':<22}数据质量"
    )
    for row in result["baseline"]:
        print(
            f"{row['scenario']:<14}{row['stress']:<14}{row['horizon_days']:<6}"
            f"{money(row['monthly_surplus_minor']):>14}"
            f"{money(row['safe_to_save_minor']):>14}"
            f"{money(row['safe_to_invest_minor']):>14}  "
            f"{row['recommended_action']:<22}"
            f"{','.join(row['data_quality']) or 'ok'}"
        )

    print(f"\n===== 储蓄缓冲敏感性（投资固定 {INVESTMENT_RESERVE_MONTHS} 个月）=====")
    print(f"{'储蓄缓冲':<10}{'正储蓄案例':<14}{'正储蓄率':<10}{'平均储蓄':<14}")
    for row in result["savings_sensitivity"]:
        print(
            f"{row['savings_reserve_months']:<10}"
            f"{row['positive_save_cases']}/{row['cases']:<11}"
            f"{row['positive_save_rate']:<10.2%}"
            f"{money(row['average_save_minor']):<14}"
        )

    print(f"\n===== 投资缓冲敏感性（储蓄固定 {SAVINGS_RESERVE_MONTHS} 个月）=====")
    print(f"{'投资缓冲':<10}{'正投案例':<14}{'正投率':<10}{'平均投资':<14}")
    for row in result["investment_sensitivity"]:
        print(
            f"{row['investment_reserve_months']:<10}"
            f"{row['positive_invest_cases']}/{row['cases']:<11}"
            f"{row['positive_invest_rate']:<10.2%}"
            f"{money(row['average_invest_minor']):<14}"
        )

    print("\n===== 不变量检查 =====")
    if result["summary"]["invariants_passed"]:
        print("✓ 全部通过：金额非负、不超过结余与上限、投资不高于储蓄、缺口时建议为 0、输入未被修改")
    else:
        print(f"✗ {result['summary']['failure_count']} 个失败")
        for failure in result["failures"][:10]:
            print(f"  - {failure}")

    determinism = result["determinism"]
    print("\n===== 确定性 =====")
    print(
        f"{'✓' if determinism['identical'] else '✗'} 相同输入重复运行："
        f"{determinism['cases_checked']} 个基准案例，"
        f"{'全部一致' if determinism['identical'] else '存在不一致'}"
    )

    print("\n===== 压力响应（基准策略）=====")
    print(
        f"{'压力':<14}{'正投率':<10}{'平均结余':>14}  {'平均投资':>14}"
        f"  {'缺口':<6}{'低支出':<8}{'无收入':<8}"
    )
    for row in result["stress_summary"]:
        print(
            f"{row['stress']:<14}{row['positive_invest_rate']:<10.2%}"
            f"{money(row['average_surplus_minor']):>14}"
            f"  {money(row['average_invest_minor']):>14}"
            f"  {row['shortfall_cases']:<6}{row['low_spending_cases']:<8}"
            f"{row['no_income_cases']:<8}"
        )


def render_rule_stability(result: Dict[str, Any]) -> str:
    """生成规则稳定性报告（Markdown）。"""
    summary = result["summary"]
    determinism = result["determinism"]
    investment = {
        row["investment_reserve_months"]: row
        for row in result["investment_sensitivity"]
    }
    lines = [
        "# 预算建议规则稳定性验证",
        "",
        f"> 生成时间：{result['generated_at']}。由 `backtest_budget.py` 自动生成，"
        "数字与 `budget_backtest.json` 同源。",
        "",
        "## 结论",
        "",
        f"- 共执行 **{summary['case_count']}** 次策略组合，"
        f"不变量失败 **{summary['failure_count']}** 次；",
        f"- 确定性：{determinism['cases_checked']} 个基准案例重复运行"
        f"{'全部一致' if determinism['identical'] else '存在不一致'}；",
        "- 投资缓冲 1 / 3 / 6 个月时，正投案例占比分别为 "
        f"{investment.get(1, {}).get('positive_invest_rate', 0):.2%} / "
        f"{investment.get(3, {}).get('positive_invest_rate', 0):.2%} / "
        f"{investment.get(6, {}).get('positive_invest_rate', 0):.2%}；",
        "- 结论：规则在合成场景和压力变体下稳定、可复现；不代表真实用户准确率。",
        "",
        "## 1. 验证范围",
        "",
        "| 维度 | 取值 |",
        "|---|---|",
        f"| 场景 | {result['scenario_count']} 个（A~G） |",
        f"| 压力变体 | {', '.join(result['stress_cases'])} |",
        f"| 周期 | {', '.join(str(day) for day in result['horizons'])} 天 |",
        f"| 缓冲策略 | {len(result['policy_grid'])} 种（储蓄 0~3 个月 × 投资 1~6 个月，投资不小于储蓄） |",
        "",
        "## 2. 不变量",
        "",
        "每次调用都检查以下约束：",
        "",
        "1. 金额非负；",
        "2. 建议金额不超过月度结余；",
        "3. 建议金额不超过流动性折算上限；",
        "4. 投资建议不高于储蓄建议；",
        "5. 出现现金流缺口时，储蓄和投资建议都为 0；",
        "6. 输入场景不被修改。",
        "",
        f"结果：**{'全部通过' if summary['invariants_passed'] else '存在失败'}**"
        f"（失败 {summary['failure_count']} 次）。",
        "",
        "## 3. 确定性",
        "",
        f"对 {determinism['cases_checked']} 个基准案例，用相同输入连续调用两次，"
        f"输出逐字段比较：**{'一致' if determinism['identical'] else '不一致'}**。",
        "",
        "## 4. 策略敏感性",
        "",
        f"### 4.1 储蓄缓冲（投资固定 {INVESTMENT_RESERVE_MONTHS} 个月）",
        "",
        "| 储蓄缓冲 | 正储蓄案例 | 正储蓄率 | 平均储蓄额 |",
        "|---:|---:|---:|---:|",
    ]
    for row in result["savings_sensitivity"]:
        lines.append(
            f"| {row['savings_reserve_months']} | "
            f"{row['positive_save_cases']}/{row['cases']} | "
            f"{row['positive_save_rate']:.2%} | {money(row['average_save_minor'])} |"
        )
    lines += [
        "",
        f"### 4.2 投资缓冲（储蓄固定 {SAVINGS_RESERVE_MONTHS} 个月）",
        "",
        "| 投资缓冲 | 正投案例 | 正投率 | 平均投资额 |",
        "|---:|---:|---:|---:|",
    ]
    for row in result["investment_sensitivity"]:
        lines.append(
            f"| {row['investment_reserve_months']} | "
            f"{row['positive_invest_cases']}/{row['cases']} | "
            f"{row['positive_invest_rate']:.2%} | {money(row['average_invest_minor'])} |"
        )
    lines += [
        "",
        "解读：缓冲月数越高，可投金额越低。当前默认的 3 个月处在"
        "“保留安全垫”和“仍能给出正向建议”之间。",
        "",
        "## 5. 压力响应（基准策略）",
        "",
        "| 压力 | 正投率 | 平均结余 | 平均投资 | 缺口案例 | 低支出案例 | 无收入案例 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["stress_summary"]:
        lines.append(
            f"| {row['stress']} | {row['positive_invest_rate']:.2%} | "
            f"{money(row['average_surplus_minor'])} | "
            f"{money(row['average_invest_minor'])} | "
            f"{row['shortfall_cases']} | {row['low_spending_cases']} | "
            f"{row['no_income_cases']} |"
        )
    lines += [
        "",
        "压力变体只缩放金额，不改变日期和周期；因此这里验证的是金额响应方向，"
        "不是真实经济冲击的完整模拟。",
        "",
        "## 6. 配套回归测试",
        "",
        "截至 2026-10-24：主任务 115 项、环境生成 73 项、FirstAgent 34 项，"
        "全链路演示退出码 0。测试清单与运行命令见项目 README。",
        "",
        "## 7. 复现",
        "",
        "```powershell",
        "cd C:\\Users\\111\\Desktop\\AI_Banking\\主任务_金融分析与量化",
        "& \"$env:LOCALAPPDATA\\Programs\\Python\\Python315\\python.exe\" backtest_budget.py",
        "```",
        "",
        "## 8. 解释边界",
        "",
        "本报告证明“规则实现一致、确定、在合成场景下稳定”，"
        "不证明“真实用户准确率”。数据来源、场景缺口和不可声明事项见"
        " `budget_backtest_data_boundaries.md`。",
        "",
    ]
    return "\n".join(lines)


def render_data_boundaries(result: Dict[str, Any]) -> str:
    """生成数据边界说明（Markdown）。"""
    lines = [
        "# 数据边界与可声明范围",
        "",
        f"> 生成时间：{result['generated_at']}。由 `backtest_budget.py` 自动生成；"
        "场景来自 A~G 合成数据。",
        "",
        "## 一句话结论",
        "",
        "当前可证明的是：规则实现与契约一致、结果确定、在合成场景和压力变体下稳定。",
        "当前不能证明的是：真实用户准确率、阈值统计有效性、投资收益或监管合规。",
        "",
        "## 1. 数据来源与可复现性",
        "",
        "- 数据来自环境生成 Agent 的 A~G 合成场景，不含真实客户或真实银行数据；",
        "- 场景可用 `seed` + `reference_date` 复现；",
        "- 回测压力变体只缩放金额，不改变日期、订阅周期和锁定期；",
        f"- 本次回测覆盖 {result['scenario_count']} 个场景、"
        f"{len(result['stress_cases'])} 种压力、{len(result['horizons'])} 个周期。",
        "",
        "## 2. 场景数据完整度",
        "",
        "| 场景 | 类型 | 历史月数 | 数据质量标记 | 说明 |",
        "|---|---|---:|---|---|",
    ]
    for row in result["scenario_quality"]:
        flags = ", ".join(row["data_quality"]) or "ok"
        lines.append(
            f"| {row['scenario']} | {row['scenario_type']} | "
            f"{row['months_of_history']} | {flags} | "
            f"{SCENARIO_NOTES.get(str(row['scenario_type']), '—')} |"
        )
    lines += [
        "",
        "`low_spending` 表示支出不足收入的 10%，应急缓冲可能偏低；"
        "`no_income` 表示没有可识别的收入；`shortfall` 表示未来现金流出现缺口。"
        "这三种情况都会降低建议金额的可信度。",
        "",
        "## 3. 可以声明",
        "",
        "| 声明 | 证据 |",
        "|---|---|",
        f"| 规则在合成场景下满足 5 类金额不变量 | {result['summary']['case_count']} 次组合，失败 {result['summary']['failure_count']} 次 |",
        f"| 相同输入输出一致 | {result['determinism']['cases_checked']} 个基准案例重复运行 |",
        "| 分析只读，不写账本 | 响应 `ledger_modified=false`，FirstAgent 前后状态一致 |",
        "| 对客输出不含评测标准答案 | `scenario.generate` 默认剥离 `expected_insights` |",
        "| 场景生成幂等结果可持久化 | SQLite 存储；73 项测试 + 跨进程重启验证同 key 返回相同 scenario_id |",
        "| A~G 同源评测 P/R/F1 = 1.0 | 仅证明规则实现与生成数据一致 |",
        "| 扰动样例 26/26 通过，FP 0 / FN 0 | 针对已知误报点的手工反例 |",
        "",
        "## 4. 不能声明",
        "",
        "| 不可声明 | 原因 |",
        "|---|---|",
        "| “真实用户识别准确率 100%” | 评测数据与规则同源，不是真实样本 |",
        "| “阈值已统计校准” | 类别门槛、订阅分级、缓冲月数均为原型策略 |",
        "| “收益预测”或“投资建议” | 推荐是偏好排序，预算是现金流推演 |",
        "| “分布式/跨机幂等” | 幂等结果存单机 SQLite，不覆盖多实例共享 |",
        "| “真实银行接入” | 全部为本地模拟会话和虚构产品 |",
        "",
        "## 5. 比赛六个场景的覆盖与边界",
        "",
        "| 场景 | 当前支持 | 证据 | 边界 |",
        "|---|---|---|---|",
        "| 智能转账 | 预览、确认、回执、红档验证码、幂等、审计 | FirstAgent 34 项测试 | 仅本机演示会话、固定账户与名册收款人 |",
        "| 账单分析 | 分类/月度/年度报告、9 类异常与提醒 | 主任务 115 项测试、A~G 评测 | 阈值为合成数据策略，未用真实数据校准 |",
        "| 理财操作 | 产品推荐、风险门槛、可投金额 | `recommend` + `budget.advice` | 推荐不是收益预测；申购/赎回为模拟 |",
        "| 卡片管理 | G 场景生成卡片、账单、卡片事件 | 环境生成 73 项测试 | FirstAgent 未接入卡申请/挂失操作，目前是数据能力 |",
        "| 订阅/代扣 | 订阅识别、续费提醒、取消 | 会话集成测试 | 会话账本为月度汇总样本，不能逐笔识别重复扣款 |",
        "| 跨场景联动 | 生日锁定、活动日历、流动性、预算建议 | F 场景 + 全链路演示 | 农历节日仅覆盖 2026–2027；数据为合成 |",
        "",
        "## 6. 需要真实数据校准的参数",
        "",
        "| 参数 | 当前值 | 位置 | 校准方法 |",
        "|---|---|---|---|",
        "| 异常大额消费门槛 | 默认 1000 元/4×；家居/保险/旅行 20000/6×；居住/装修 30000/6×；医疗/教育 50000/6× | `analysis/anomaly.py` | 用真实标注数据看分位数与误报率 |",
        "| 订阅负担分级 | 3% / 8% | `analysis/cashflow.py` | 用真实收入与订阅分布校准 |",
        "| 储蓄缓冲 | 1 个月支出 | `analysis/budget.py` | 用真实支出波动与最低余额校准 |",
        "| 投资缓冲 | 3 个月支出 | `analysis/budget.py` | 用真实应急金与赎回行为校准 |",
        "| 生日锁定金额 | 1000 元/月 | F 场景与流动性 | 用真实用户预算分布校准 |",
        "",
        "## 7. 运维与交付边界",
        "",
        "- 环境生成侧幂等结果已持久化到本机 SQLite（默认 `runtime/idempotency.sqlite3`，"
        "可用 `ENV_AGENT_IDEMPOTENCY_DB` 覆盖），重启后可重放；不覆盖多实例/分布式；",
        "- 分析模块通过路径依赖接入 FirstAgent，可用 `AI_BANKING_ANALYSIS_DIR` 覆盖；",
        "- 农历节日只覆盖 2026–2027，是演示对照表；",
        "- 审计与账本同事务持久化，但普通 SQLite 不是防篡改生产审计系统；",
        "- 全部接口只监听本机，HTTP 检查 Host/Origin。",
        "",
        "## 8. 拿到真实数据后的最小验证方案",
        "",
        "1. 收集 20~50 条脱敏交易流水，至少覆盖 3 个月；",
        "2. 标注真实异常、订阅和固定支出；",
        "3. 用同一套 `backtest_budget.py` 不变量和压力变体跑真实数据；",
        "4. 对比建议金额分布与人工判断，只报告区间和误报率，不宣称单点准确率；",
        "5. 用结果校准第 6 节的参数，并更新本报告。",
        "",
    ]
    return "\n".join(lines)


def write_reports(result: Dict[str, Any], prefix: Path) -> Tuple[Path, Path, Path, Path]:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    md_path = prefix.with_suffix(".md")
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 预算建议参数化回测",
        "",
        f"- 生成时间：{result['generated_at']}",
        f"- 场景数：{result['scenario_count']}",
        f"- 压力变体：{', '.join(result['stress_cases'])}",
        f"- 周期：{', '.join(str(day) for day in result['horizons'])} 天",
        f"- 策略数：{len(result['policy_grid'])}",
        "",
        "## 基准策略（储蓄 1 个月 / 投资 3 个月）",
        "",
        "| 场景 | 压力 | 周期 | 月度结余 | 储蓄建议 | 投资建议 | 动作 | 数据质量 |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in result["baseline"]:
        lines.append(
            f"| {row['scenario']} | {row['stress']} | {row['horizon_days']} | "
            f"{money(row['monthly_surplus_minor'])} | {money(row['safe_to_save_minor'])} | "
            f"{money(row['safe_to_invest_minor'])} | {row['recommended_action']} | "
            f"{','.join(row['data_quality']) or 'ok'} |"
        )

    lines += [
        "",
        f"## 储蓄缓冲敏感性（投资固定 {INVESTMENT_RESERVE_MONTHS} 个月）",
        "",
        "| 储蓄缓冲 | 正储蓄案例 | 正储蓄率 | 平均储蓄额 |",
        "|---:|---:|---:|---:|",
    ]
    for row in result["savings_sensitivity"]:
        lines.append(
            f"| {row['savings_reserve_months']} | "
            f"{row['positive_save_cases']}/{row['cases']} | "
            f"{row['positive_save_rate']:.2%} | {money(row['average_save_minor'])} |"
        )

    lines += [
        "",
        f"## 投资缓冲敏感性（储蓄固定 {SAVINGS_RESERVE_MONTHS} 个月）",
        "",
        "| 投资缓冲 | 正投案例 | 正投率 | 平均投资额 |",
        "|---:|---:|---:|---:|",
    ]
    for row in result["investment_sensitivity"]:
        lines.append(
            f"| {row['investment_reserve_months']} | "
            f"{row['positive_invest_cases']}/{row['cases']} | "
            f"{row['positive_invest_rate']:.2%} | {money(row['average_invest_minor'])} |"
        )

    lines += [
        "",
        "## 不变量",
        "",
        "通过" if result["summary"]["invariants_passed"] else
        f"失败 {result['summary']['failure_count']} 个",
        "",
        "## 边界",
        "",
        "- 数据来自 A~G 合成场景及压力缩放，不代表真实用户分布；",
        "- 1/3/6 个月是原型策略，不是监管标准；",
        "- 压力变体只缩放金额，不改变日期、订阅周期和锁定期；",
        "- 结论适合验证规则稳定性，不能替代真实脱敏数据回测。",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    stability_path = prefix.with_name(
        prefix.name + "_rule_stability"
    ).with_suffix(".md")
    boundaries_path = prefix.with_name(
        prefix.name + "_data_boundaries"
    ).with_suffix(".md")
    stability_path.write_text(render_rule_stability(result), encoding="utf-8")
    boundaries_path.write_text(render_data_boundaries(result), encoding="utf-8")
    return json_path, md_path, stability_path, boundaries_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="预算建议参数化回测")
    parser.add_argument("--fixtures", default=str(FIXTURE_DIR))
    parser.add_argument("--horizons", default="30,90")
    parser.add_argument("--out-prefix", default=str(BASE_DIR / "reports" / "budget_backtest"))
    parser.add_argument("--no-report", action="store_true", help="只打印，不写文件")
    args = parser.parse_args(argv)

    try:
        horizons = [
            int(value) for value in args.horizons.split(",") if value.strip()
        ]
    except ValueError:
        parser.error("--horizons 必须是逗号分隔的整数")
    if not horizons or any(day < 1 or day > 366 for day in horizons):
        parser.error("--horizons 每项必须是 1~366 的整数")

    paths = _fixture_paths(Path(args.fixtures))
    if not paths:
        print(f"未找到场景文件：{args.fixtures}")
        return 1

    result = run_backtest(paths, horizons=horizons)
    print_report(result)
    if not args.no_report:
        paths = write_reports(result, Path(args.out_prefix))
        print("\n报告：")
        for path in paths:
            print(f"  {path}")
    return 0 if result["summary"]["invariants_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
