#!/usr/bin/env python3
"""demo_full_chain.py —— 比赛演示：转账 → 账单分析 → 订阅续费 → 生日锁定 → 流动性。

一条命令串起两个模块，但不复制它们的代码：

- Desktop/FirstAgent：持久化会话账本，真实执行一次模拟转账（预览 → 确认 → 回执）；
- 主任务_金融分析与量化：对会话账本做只读分析，并生成 F 场景演示生日预算锁定
  与跨场景流动性。

运行（在本文件所在目录）：

    python demo_full_chain.py
    python demo_full_chain.py --amount-minor 120000 --seed 42 --reference-date 2026-10-23
    python demo_full_chain.py --db runtime/demo.sqlite3

脚本退出码：0 全部通过，1 任一步失败。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
FIRST_AGENT_DIR = ROOT.parent / "FirstAgent"
ANALYSIS_DIR = ROOT / "主任务_金融分析与量化"

VERIFY_CODE = "246810"  # FirstAgent 演示验证码（红档转账才需要）
F_PROMPT = "配偶生日快到了，想锁定 1000 元预算，并提醒我提前订鲜花和蛋糕"
F_SCENARIO_TYPE = "F"


class DemoError(RuntimeError):
    pass


def _prepare_paths() -> None:
    for path in (FIRST_AGENT_DIR, ANALYSIS_DIR):
        if not path.exists():
            raise DemoError(f"找不到依赖模块：{path}")
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


_prepare_paths()

from bridge import generate_scenario  # noqa: E402
from cli import (  # noqa: E402
    print_budget,
    print_burden,
    print_findings,
    print_liquidity,
    print_report,
)
from pipeline import run_pipeline  # noqa: E402

from first_agent.service import AgentService  # noqa: E402


# ---------------------------------------------------------------- 输出工具

def step(number: int, title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"步骤 {number}：{title}")
    print("=" * 70)


def money(amount_minor: Optional[int]) -> str:
    if amount_minor is None:
        return "无数据"
    return f"¥{amount_minor / 100:,.2f}"


def ok(message: str) -> None:
    print(f"  ✓ {message}")


# ---------------------------------------------------------------- 工具调用

class Session:
    """FirstAgent 会话的薄封装：自动分配幂等键并校验响应。"""

    def __init__(self, service: AgentService, sid: str) -> None:
        self.service = service
        self.sid = sid
        self._counter = 0

    def call(
        self,
        action: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        require_success: bool = True,
    ) -> Dict[str, Any]:
        self._counter += 1
        response = self.service.call(
            self.sid, action, args or {}, f"demo-key-{self._counter}"
        )
        if require_success and response.get("status") != "succeeded":
            error = response.get("error") or {}
            raise DemoError(
                f"{action} 失败：{error.get('code')} {error.get('message')}"
            )
        return response

    def state(self) -> Dict[str, Any]:
        return self.call("snapshot")["data"]["state"]

    def analysis(self, tool: str, args: Optional[Dict[str, Any]] = None) -> Any:
        response = self.call("analysis", {"tool": tool, "args": args or {}})
        payload = response["data"]
        if payload.get("ledger_modified"):
            raise DemoError(f"{tool} 报告 ledger_modified=true，违反只读约定")
        return payload["result"]


# ---------------------------------------------------------------- 各步骤

def do_authorize(session: Session) -> None:
    session.call(
        "rpc",
        {"method": "authorize", "args": [{"read": True, "subscriptions": True, "trade": True}]},
    )
    ok("已授权：账户读取 + 订阅读取 + 转账")


def do_transfer(session: Session, amount_minor: int, beneficiary: str) -> Dict[str, Any]:
    before = session.call("accounts")["data"]

    preview_response = session.call(
        "transfer.preview",
        {"amount_minor": amount_minor, "beneficiary_name": beneficiary},
        require_success=False,
    )
    if preview_response.get("error"):
        error = preview_response["error"]
        raise DemoError(f"转账预览失败：{error.get('code')} {error.get('message')}")
    preview = preview_response["data"]
    if preview.get("status") != "awaiting_confirmation":
        raise DemoError(f"转账预览状态异常：{preview.get('status')}")
    print(
        f"  预览：{beneficiary}  {money(preview['amount'])}  "
        f"风险档 {preview['level']}  操作号 {preview['id'][:12]}…"
    )

    confirm_args: Dict[str, Any] = {
        "operation_id": preview["id"],
        "confirmed": True,
    }
    # 红档（累计超过 1000 元）需要与预览绑定的演示验证断言
    if preview["level"] == "red":
        assertion = session.call(
            "transfer.verify", {"operation_id": preview["id"], "code": VERIFY_CODE}
        )["data"]
        confirm_args["assertion_id"] = assertion["assertion_id"]
        ok("红档转账：已完成演示验证")

    receipt = session.call("transfer.confirm", confirm_args)["data"]
    if receipt.get("status") != "succeeded":
        raise DemoError(f"转账未成功：{receipt.get('status')}")

    after = session.call("accounts")["data"]
    expected = before["available_minor"] - amount_minor
    if after["available_minor"] != expected:
        raise DemoError(
            f"余额不符：期望 {money(expected)}，实际 {money(after['available_minor'])}"
        )
    if after["version"] != before["version"] + 1:
        raise DemoError("账本版本未按预期递增")

    print(f"  回执：{receipt.get('receipt_id', '')[:20]}…")
    print(
        f"  余额：{money(before['available_minor'])} → "
        f"{money(after['available_minor'])}  版本 {before['version']} → {after['version']}"
    )
    ok("转账已入账，回执、余额、版本三者一致")
    return after


def do_bills(session: Session, month: str) -> Dict[str, Any]:
    report = session.analysis("bills.summary", {"month": month})
    print_report(report)
    if report.get("income_minor", 0) <= 0:
        raise DemoError("账单报告没有收入数据")
    ok("账单报告与账本口径一致（整数分、只统计 booked）")
    return report


def do_subscriptions(session: Session) -> Dict[str, Any]:
    burden = session.analysis("subscriptions.burden")
    print_burden(burden)
    if burden["active_count"] <= 0:
        raise DemoError("没有可演示的 active 订阅")

    findings = session.analysis("anomalies.detect")
    renewals = [f for f in findings if f["insight_type"] == "subscription_renewal"]
    print_findings(renewals)
    if not renewals:
        raise DemoError("没有识别到订阅续费提醒")
    ok(f"订阅负担 {money(burden['monthly_total_minor'])}/月，"
       f"{len(renewals)} 条续费提醒")
    return burden


def do_birthday_liquidity(
    seed: int, reference_date: str, days: int
) -> Dict[str, Any]:
    scenario = generate_scenario(
        F_PROMPT,
        scenario_type=F_SCENARIO_TYPE,
        seed=seed,
        reference_date=reference_date,
    )
    if "expected_insights" not in scenario:
        raise DemoError("F 场景缺少 expected_insights，无法做防作弊对照")

    # 以场景参考日期作为"今天"，保证演示结果与运行机器的实际日期无关
    as_of = date.fromisoformat(reference_date)
    payload = run_pipeline(
        scenario=scenario, days=days, include_evaluation=False, today=as_of
    )
    if payload.get("status") != "succeeded":
        raise DemoError(f"F 场景分析失败：{payload.get('error')}")
    if payload.get("ledger_modified"):
        raise DemoError("F 场景分析报告 ledger_modified=true")
    if "evaluation" in payload:
        raise DemoError("对客结果里泄漏了 evaluation 标准答案")

    birthdays = [
        f for f in payload["findings"]
        if f["insight_type"] in {"birthday_upcoming", "budget_lock"}
    ]
    print_findings(birthdays)
    print_liquidity(payload["liquidity"])

    # 把标准答案删掉再跑一遍：结果必须完全一致，证明分析没有"抄答案"
    stripped = {k: v for k, v in scenario.items() if k != "expected_insights"}
    again = run_pipeline(
        scenario=stripped, days=days, include_evaluation=False, today=as_of
    )
    for key in ("findings", "liquidity", "report"):
        if again[key] != payload[key]:
            raise DemoError(f"移除 expected_insights 后 {key} 发生变化，分析可能读取了标准答案")
    ok("移除 expected_insights 后结果一致：分析只读流水，不读标准答案")

    if not payload["liquidity"]["lock_active"]:
        raise DemoError("生日预算未处于锁定状态")
    if not any(f["insight_type"] == "budget_lock" for f in payload["findings"]):
        raise DemoError("没有识别到预算锁定提醒")
    return payload


def verify_ledger_untouched(session: Session, before: Dict[str, Any]) -> None:
    after = session.state()
    if after != before:
        raise DemoError("只读分析期间会话账本发生变化")
    ok("全部分析前后账本状态逐字段一致")


# ---------------------------------------------------------------- 主流程

def run(args: argparse.Namespace) -> int:
    temp: Optional[tempfile.TemporaryDirectory] = None
    if args.db:
        db_path = Path(args.db)
    else:
        temp = tempfile.TemporaryDirectory(prefix="ai-banking-demo-")
        db_path = Path(temp.name) / "demo.sqlite3"

    try:
        print("AI Banking 全链路演示")
        print(f"会话账本：{db_path}")

        service = AgentService(db_path)
        session = Session(service, service.create_session())

        step(1, "授权与会话")
        ok(f"已创建本地演示会话（SQLite 持久化）")
        do_authorize(session)

        step(2, "转账：预览 → 确认 → 入账")
        do_transfer(session, args.amount_minor, args.beneficiary)

        snapshot_before = session.state()
        month = args.month or _latest_month(snapshot_before)

        step(3, "账单分析（只读）")
        report = do_bills(session, month)

        step(4, "订阅负担、续费提醒与预算建议（只读）")
        burden = do_subscriptions(session)
        live_advice = session.analysis("budget.advice", {"days": args.days})
        print_budget(live_advice, show_warnings=False)
        recommendation = session.call("recommend", {"top_k": 3})["data"]
        basis = recommendation["budget_basis"]
        products = "、".join(
            item["product_id"] for item in recommendation["recommendations"]
        ) or "无可推荐产品"
        print(
            f"  理财推荐：{products}  可投上限 {money(basis['applied_minor'])}"
            f"（来源 {basis['source']}）"
        )
        if basis["analysis_headroom_minor"] == 0:
            print("  [推荐] 分析建议先补应急金，以上仅作偏好排序参考")

        step(5, "生日预算锁定与跨场景流动性（F 场景，只读）")
        f_result = do_birthday_liquidity(
            args.seed, args.reference_date, args.days
        )

        step(6, "只读性校验")
        verify_ledger_untouched(session, snapshot_before)

        step(7, "演示结果汇总")
        liquidity = f_result["liquidity"]
        print(f"  转账金额        ：{money(args.amount_minor)} → {args.beneficiary}")
        print(f"  本月收入 / 消费 ：{money(report['income_minor'])} / "
              f"{money(report['spending_minor'])}")
        print(f"  订阅月均支出    ：{money(burden['monthly_total_minor'])}"
              f"（占工资 {_percent(burden['burden_ratio'])}）")
        print(f"  生日锁定预算    ：{money(liquidity['locked_amount_minor'])}，"
              f"已计划活动 {money(liquidity['planned_activity_minor'])}")
        print(f"  现在可动用      ：{money(liquidity['safe_to_spend_now_minor'])}")
        print(f"  锁定预算被挤占  ：{money(liquidity['locked_amount_at_risk_minor'])}")
        print(
            f"  会话储蓄/投资   ：{money(live_advice['savings']['safe_monthly_minor'])} / "
            f"{money(live_advice['investment']['safe_monthly_minor'])} 每月"
            f"（{live_advice['recommended_action']}）"
        )
        f_budget = f_result["budget_advice"]
        print(
            f"  F 场景储蓄/投资 ：{money(f_budget['savings']['safe_monthly_minor'])} / "
            f"{money(f_budget['investment']['safe_monthly_minor'])} 每月"
            f"（{f_budget['recommended_action']}）"
        )
        print("\n演示完成：全部步骤通过。")
        return 0
    finally:
        if temp is not None:
            temp.cleanup()


def _latest_month(state: Dict[str, Any]) -> str:
    dates: List[str] = [
        item.get("date", "")
        for item in state.get("transactions", [])
        if item.get("date")
    ]
    if not dates:
        raise DemoError("会话账本没有交易，无法确定统计月份")
    return max(dates)[:7]


def _percent(ratio: Optional[float]) -> str:
    return "无工资数据" if ratio is None else f"{ratio:.2%}"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AI Banking 全链路演示")
    parser.add_argument("--amount-minor", type=int, default=80000,
                        help="转账金额（整数分），默认 800 元")
    parser.add_argument("--beneficiary", default="张三", help="收款人姓名")
    parser.add_argument("--month", help="账单月份 YYYY-MM，默认取账本最新月份")
    parser.add_argument("--seed", type=int, default=42, help="F 场景随机种子")
    parser.add_argument("--reference-date", default="2026-10-23",
                        help="F 场景参考日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30, help="现金流/流动性投影天数")
    parser.add_argument("--db", help="会话 SQLite 路径，默认使用临时库")
    args = parser.parse_args(argv)

    if not 1 <= args.amount_minor <= 1_000_000_000:
        parser.error("--amount-minor 必须是 1~1000000000 的整数分")
    if not 1 <= args.days <= 366:
        parser.error("--days 必须是 1~366")

    try:
        return run(args)
    except DemoError as exc:
        print(f"\n演示失败：{exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        # AgentService 在缺少 Node.js 时抛 RuntimeError
        print(f"\n演示失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
