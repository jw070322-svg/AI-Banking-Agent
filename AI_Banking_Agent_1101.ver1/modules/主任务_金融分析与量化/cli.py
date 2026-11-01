"""cli.py —— 账单分析与异常识别命令行。

用法：
    python cli.py make-fixtures
    python cli.py report fixtures/SCENARIO_A.json --month 2026-10
    python cli.py report fixtures/SCENARIO_A.json --year 2026 --json
    python cli.py evaluate fixtures
    python cli.py evaluate fixtures/SCENARIO_C.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from analysis import (
    annual_report,
    available_liquidity,
    detect_anomalies,
    evaluate_detection,
    load_scenario,
    monthly_report,
    overall_summary,
    project_cashflow,
    subscription_burden,
)
from analysis.evaluate import aggregate_evaluations


def money(amount_minor: int) -> str:
    """整数分 -> 可读人民币。"""
    return f"¥{amount_minor / 100:,.2f}"


def print_report(report: Dict[str, Any]) -> None:
    title = report.get("month") or f"{report.get('year', '')} 年度"
    print(f"\n===== 账单报告 {title} =====")
    print(f"收入      ：{money(report.get('income_minor', 0))}")
    print(f"消费      ：{money(report.get('spending_minor', 0))}")
    print(f"转出      ：{money(report.get('transfer_out_minor', 0))}")
    print(f"净额      ：{money(report.get('net_minor', 0))}")
    print(f"交易笔数  ：{report.get('transaction_count', 0)}")

    print("\n-- 消费分类 --")
    for row in report.get("categories", []):
        print(
            f"  {row['category']:<6} {money(row['spending_minor']):>14}"
            f"  {row['share_bp'] / 100:5.1f}%  {row['transaction_count']} 笔"
        )

    if report.get("top_merchants"):
        print("\n-- 商户排行 --")
        for row in report["top_merchants"]:
            print(f"  {row['merchant']:<12} {money(row['spending_minor']):>14}")

    if report.get("credit_card"):
        bill = report["credit_card"]
        print("\n-- 信用卡 --")
        print(
            f"  账单日 {bill.get('statement_date')}  还款日 {bill.get('due_date')}"
            f"  未还 {money(bill.get('outstanding_amount_minor', 0))}"
            f"  状态 {bill.get('status')}"
        )

    if report.get("months"):
        print("\n-- 月度趋势 --")
        for row in report["months"]:
            print(
                f"  {row['month']}  收入 {money(row['income_minor']):>14}"
                f"  消费 {money(row['spending_minor']):>14}"
                f"  净额 {money(row['net_minor']):>14}"
            )


def print_findings(findings: List[Dict[str, Any]]) -> None:
    print(f"\n===== 异常与提醒（{len(findings)} 条）=====")
    for item in findings:
        print(f"[{item['severity']:<6}] {item['date']}  {item['insight_type']:<20} {item['title']}")


def print_burden(burden: Dict[str, Any]) -> None:
    print("\n===== 订阅负担 =====")
    print(f"订阅数量  ：{burden['active_count']}")
    print(f"月均支出  ：{money(burden['monthly_total_minor'])}")
    print(f"年度支出  ：{money(burden['annual_total_minor'])}")
    print(f"月收入    ：{money(burden['monthly_income_minor'])}")
    ratio = burden["burden_ratio"]
    print(f"占收入比  ：{ratio:.2%}" if ratio is not None else "占收入比  ：无工资数据")
    print(f"负担等级  ：{burden['burden_level'] or '未知'}")
    print(f"7 天内扣费：{money(burden['upcoming_7_days_minor'])}")
    print(f"30 天内扣费：{money(burden['upcoming_30_days_minor'])}")
    for item in burden["items"]:
        print(
            f"  {item['merchant']:<12} {money(item['amount_minor']):>10}/{item['cycle']}"
            f"  折合月度 {money(item['monthly_equivalent_minor'])}"
            f"  下次 {item['next_charge_date']}（{item['days_until_charge']} 天）"
        )


def print_cashflow(projection: Dict[str, Any]) -> None:
    print(f"\n===== 现金流投影 {projection['horizon_days']} 天 =====")
    print(f"期初余额  ：{money(projection['starting_balance_minor'])}")
    print(f"预计收入  ：{money(projection['expected_income_minor'])}")
    print(f"计划支出  ：{money(projection['scheduled_outflow_minor'])}")
    print(f"期末余额  ：{money(projection['ending_balance_minor'])}")
    print(
        f"最低余额  ：{money(projection['lowest_balance_minor'])}"
        f"（{projection['lowest_balance_date']}）"
    )
    if projection["shortfall_days"]:
        print(f"缺口日期  ：{', '.join(projection['shortfall_days'])}")
    print("\n-- 事件 --")
    for event in projection["events"]:
        print(
            f"  {event['date']}  {event['event_type']:<16}"
            f" {money(event['amount_minor']):>12}  {event['title']}"
            f"  余额 {money(event['balance_after_minor'])}"
        )
    for warning in projection["warnings"]:
        print(f"[警告] {warning}")


def print_liquidity(liquidity: Dict[str, Any], show_warnings: bool = True) -> None:
    print("\n===== 可用流动性（跨场景）=====")
    print(f"当前余额      ：{money(liquidity['current_balance_minor'])}")
    print(
        f"锁定金额      ：{money(liquidity['locked_amount_minor'])}"
        f"{'' if liquidity['lock_active'] else '（锁定月份已过，已释放）'}"
    )
    print(f"已计划生日活动：{money(liquidity['planned_activity_minor'])}")
    print(f"剩余预留      ：{money(liquidity['reserved_remaining_minor'])}")
    print(f"未来义务合计  ：{money(liquidity['upcoming_obligations_minor'])}")
    print(f"预计收入      ：{money(liquidity['expected_income_minor'])}")
    print(
        f"最低余额      ：{money(liquidity['minimum_balance_minor'])}"
        f"（{liquidity['minimum_balance_date']}）"
    )
    print(f"现在可动用    ：{money(liquidity['safe_to_spend_now_minor'])}")
    print(f"计入未来工资后：{money(liquidity['safe_to_spend_horizon_minor'])}")
    print(f"锁定预算被挤占：{money(liquidity['locked_amount_at_risk_minor'])}")
    if not show_warnings:
        return
    projection_warnings = set(
        (liquidity.get("projection") or {}).get("warnings", [])
    )
    for warning in liquidity.get("warnings", []):
        if warning not in projection_warnings:
            print(f"[流动性] {warning}")


_CONSTRAINT_LABELS = {
    "monthly_surplus": "月度结余",
    "liquidity_reserve": "流动性缓冲",
    "cashflow_shortfall": "现金流缺口",
    "insufficient_income": "缺少收入数据",
    "both": "结余与缓冲同时触顶",
}


def print_budget(advice: Dict[str, Any], show_warnings: bool = True) -> None:
    print("\n===== 每月可安全储蓄/投资 =====")
    print(f"统计月份  ：{advice['basis_month'] or '全部'}")
    print(f"月度结余  ：{money(advice['monthly_surplus_minor'])}")
    savings = advice["savings"]
    investment = advice["investment"]
    print(
        f"储蓄建议  ：{money(savings['safe_monthly_minor'])}/月"
        f"（保留 {advice['policy']['savings_reserve_months']} 个月支出，"
        f"受限于{_CONSTRAINT_LABELS.get(savings['binding_constraint'], savings['binding_constraint'])}）"
    )
    print(
        f"投资建议  ：{money(investment['safe_monthly_minor'])}/月"
        f"（保留 {advice['policy']['investment_reserve_months']} 个月支出，"
        f"受限于{_CONSTRAINT_LABELS.get(investment['binding_constraint'], investment['binding_constraint'])}）"
    )
    print(f"建议动作  ：{advice['recommended_action']}")
    if not show_warnings:
        return
    for warning in advice["warnings"]:
        print(f"[预算] {warning}")


def print_evaluation(result: Dict[str, Any]) -> None:
    summary = result["summary"]
    print("\n===== 识别效果 =====")
    print(
        f"标准答案 {summary['expected']} 条，识别 {summary['detected']} 条，"
        f"TP {summary['tp']} / FP {summary['fp']} / FN {summary['fn']}"
    )
    print(
        f"精确率 {summary['precision']:.2%}  "
        f"召回率 {summary['recall']:.2%}  "
        f"F1 {summary['f1']:.2%}"
    )
    print("\n-- 分类型 --")
    for insight_type, row in result["by_type"].items():
        print(
            f"  {insight_type:<22} 期望 {row['expected']:>2}  识别 {row['detected']:>2}"
            f"  P {row['precision']:.2f}  R {row['recall']:.2f}  F1 {row['f1']:.2f}"
        )
    if result.get("missed"):
        print("\n漏报：")
        for item in result["missed"]:
            print(f"  - {item['insight_type']} {item['date']} {item['title']}")
    if result.get("false_positives"):
        print("\n误报：")
        for item in result["false_positives"]:
            print(f"  - {item['insight_type']} {item['date']} {item['title']}")


def _scenario_files(path: Path) -> List[Path]:
    if path.is_dir():
        return sorted(path.glob("*.json"))
    return [path]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Banking 账单分析 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    fixtures = sub.add_parser("make-fixtures", help="用环境生成 Agent 生成固定样例")
    fixtures.add_argument("--seed", type=int, default=42)
    fixtures.add_argument("--reference-date", default="2026-10-23")

    report = sub.add_parser("report", help="账单报告 + 异常识别")
    report.add_argument("file")
    report.add_argument("--month", help="YYYY-MM，例如 2026-10")
    report.add_argument("--year", type=int, help="年度报告，例如 2026")
    report.add_argument("--json", action="store_true", help="输出 JSON")

    evaluate = sub.add_parser("evaluate", help="用标准答案评估识别效果")
    evaluate.add_argument("path", help="场景 JSON 或包含场景的目录")
    evaluate.add_argument("--json", action="store_true")

    perturb = sub.add_parser("perturb", help="运行扰动/对抗样例，检查误报")
    perturb.add_argument("--json", action="store_true")

    flow = sub.add_parser("cashflow", help="订阅负担 + 未来现金流投影")
    flow.add_argument("file")
    flow.add_argument("--days", type=int, default=30, help="投影天数（1~366）")
    flow.add_argument("--json", action="store_true")

    pipe = sub.add_parser("pipeline", help="环境生成 → 分析 → 主 Agent 结果")
    pipe.add_argument("--prompt", help="自然语言需求（不提供 --file 时生成新场景）")
    pipe.add_argument("--file", help="已有场景 JSON")
    pipe.add_argument("--scenario-type", choices=list("ABCDEFG"))
    pipe.add_argument("--seed", type=int)
    pipe.add_argument("--reference-date")
    pipe.add_argument("--days", type=int, default=30)
    pipe.add_argument("--month")
    pipe.add_argument("--evaluate", action="store_true", help="附带标准答案评测")
    pipe.add_argument("--json", action="store_true")

    tools_cmd = sub.add_parser("tools", help="查看/调用主 Agent 分析工具")
    tools_cmd.add_argument("--list", action="store_true")
    tools_cmd.add_argument("--call", metavar="NAME")
    tools_cmd.add_argument("--args", default="{}", help="工具参数 JSON")
    tools_cmd.add_argument("--file", help="场景 JSON（作为工具上下文）")
    tools_cmd.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "pipeline":
        from bridge import BridgeError
        from pipeline import format_summary, run_pipeline

        scenario = load_scenario(args.file) if args.file else None
        if scenario is None and not args.prompt:
            print("必须提供 --prompt 或 --file", file=sys.stderr)
            return 2
        try:
            result = run_pipeline(
                prompt=args.prompt,
                scenario=scenario,
                scenario_type=args.scenario_type,
                seed=args.seed,
                reference_date=args.reference_date,
                days=args.days,
                month=args.month,
                include_evaluation=args.evaluate,
            )
        except (BridgeError, ValueError) as exc:
            print(f"处理失败：{exc}", file=sys.stderr)
            return 1

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            meta = result["scenario"]
            print(f"场景：{meta['scenario_id']}  类型：{meta['scenario_type']}")
            print(format_summary(result))
            print_report(result["report"])
            print_findings(result["findings"])
            print_burden(result["subscription_burden"])
            print_cashflow(result["cashflow"])
            print_liquidity(result["liquidity"], show_warnings=False)
            print_budget(result["budget_advice"], show_warnings=False)
            for warning in result["warnings"]:
                print(f"[警告] {warning}")
        return 0

    if args.command == "tools":
        from tools import call_tool, list_tools

        if args.list:
            specs = list_tools()
            if args.json:
                print(json.dumps(specs, ensure_ascii=False, indent=2))
            else:
                for spec in specs:
                    print(f"{spec['name']:<22} {spec['description']}")
            return 0

        if not args.call:
            print("请提供 --list 或 --call NAME", file=sys.stderr)
            return 2

        try:
            tool_args = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(f"--args 不是合法 JSON：{exc}", file=sys.stderr)
            return 2

        data = load_scenario(args.file) if args.file else None
        result = call_tool(args.call, tool_args, data=data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "succeeded" else 1

    if args.command == "cashflow":
        data = load_scenario(args.file)
        try:
            projection = project_cashflow(data, days=args.days)
        except ValueError as exc:
            print(f"参数错误：{exc}", file=sys.stderr)
            return 2
        burden = subscription_burden(data)
        liquidity = available_liquidity(data, days=args.days)
        if args.json:
            print(json.dumps(
                {
                    "subscription_burden": burden,
                    "cashflow": projection,
                    "liquidity": {
                        key: value for key, value in liquidity.items()
                        if key != "projection"
                    },
                },
                ensure_ascii=False, indent=2,
            ))
        else:
            print(f"场景：{data.get('scenario_id')}  类型：{data.get('scenario_type')}")
            print_burden(burden)
            print_cashflow(projection)
            print_liquidity(liquidity)
        return 0

    if args.command == "perturb":
        from perturbations import print_results, run_cases
        result = run_cases()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print_results(result)
        return 0 if result["summary"]["passed"] == result["summary"]["total"] else 1

    if args.command == "make-fixtures":
        from make_fixtures import build_all
        for path in build_all(args.seed, args.reference_date):
            print(f"已生成：{path}")
        return 0

    if args.command == "report":
        data = load_scenario(args.file)
        if args.year is not None:
            financial = annual_report(data, args.year)
        elif args.month is not None:
            financial = monthly_report(data, args.month)
        else:
            financial = overall_summary(data)
        findings = detect_anomalies(data)

        if args.json:
            print(json.dumps(
                {"report": financial, "findings": findings},
                ensure_ascii=False, indent=2,
            ))
        else:
            print(f"场景：{data.get('scenario_id')}  类型：{data.get('scenario_type')}")
            print_report(financial)
            print_findings(findings)
        return 0

    if args.command == "evaluate":
        files = _scenario_files(Path(args.path))
        if not files:
            print("没有找到场景文件", file=sys.stderr)
            return 1
        results = []
        for path in files:
            data = load_scenario(path)
            result = evaluate_detection(data)
            results.append(result)
            if not args.json and len(files) > 1:
                summary = result["summary"]
                print(
                    f"{path.name:<24} P {summary['precision']:.2f}  "
                    f"R {summary['recall']:.2f}  F1 {summary['f1']:.2f}"
                )
        output = results[0] if len(results) == 1 else aggregate_evaluations(results)
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print_evaluation(output)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
