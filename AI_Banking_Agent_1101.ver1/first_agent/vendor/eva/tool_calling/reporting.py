"""Evidence-grounded Markdown report generation.

The generator only renders structured data that Module 6 tools returned. It
never invents balances, rates, risk approvals, or compliance conclusions. It
also refuses to imply that the completed Risk Engine/Compliance Guard ran when
the per-call safety metadata says they were not connected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .orchestration import OrchestrationResult
from .utils import deep_copy_json


_STATUS_LABELS = {
    "success": "成功",
    "error": "失败",
    "unknown": "结果未知",
    "skipped": "跳过",
    "blocked": "被依赖阻断",
    "not_run": "未执行",
    "completed": "已完成",
    "partially_completed": "部分完成",
    "failed": "失败",
}


class MarkdownReportGenerator:
    def render(
        self,
        result: OrchestrationResult,
        *,
        title: str = "AI 银行智能体 · 工具证据报告",
    ) -> str:
        if not isinstance(result, OrchestrationResult):
            raise TypeError("render() requires an OrchestrationResult")
        lines: list[str] = [
            f"# {title}",
            "",
            f"- 计划：`{result.plan_id}`",
            f"- Trace：`{result.trace_id}`",
            f"- 生成时间：{result.finished_at}",
            f"- 执行状态：**{_STATUS_LABELS.get(result.status, result.status)}**",
            f"- 用户目标：{result.goal or '未提供'}",
            "",
            "> 本报告只汇总本次工具调用的结构化输出，是原型演示材料，"
            "不构成金融、投资或信贷建议，也不构成交易授权。",
            "",
        ]
        any_simulated = any(
            item.simulated for item in result.evidence.items
        )
        if any_simulated:
            lines.extend(
                [
                    "> 本次结果包含模拟数据/模拟交易。模拟回执不是真实付款凭证。",
                    "",
                ]
            )
        lines.extend(
            [
                "> 除非下方“安全与集成状态”明确显示 "
                "`production_checks_active=true`，本报告**不**声称已完成的 "
                "Risk Engine 或 Compliance Guard 参与了本次调用。",
                "",
                "## 执行概览",
                "",
                result.summary,
                "",
                "| 步骤 | 工具 | 状态 | 输出摘要 / 原因 |",
                "|---|---|---|---|",
            ]
        )
        for step in result.steps:
            if step.result and step.result.ok:
                output = step.result.summary
            elif step.result and step.result.error:
                output = step.result.error.message
            else:
                output = step.skip_reason or step.skip_detail or ""
            lines.append(
                "| {step} | {tool} | {status} | {output} |".format(
                    step=_md(step.step_id),
                    tool=_md(step.tool),
                    status=_md(_STATUS_LABELS.get(step.status, step.status)),
                    output=_md(output),
                )
            )
        lines.append("")

        successful = [
            step for step in result.steps if step.status == "success" and step.result
        ]
        if successful:
            lines.extend(["## 结构化发现", ""])
            for index, step in enumerate(successful, start=1):
                call = step.result
                assert call is not None
                lines.append(
                    f"### {index}. {step.label} · `{step.tool}@{call.version}`"
                )
                lines.append("")
                if call.duplicate:
                    lines.extend(
                        [
                            "> 幂等重放：返回原始结果，未重复执行副作用。",
                            "",
                        ]
                    )
                if call.summary:
                    lines.extend([call.summary, ""])
                lines.extend(self._render_tool_data(step.tool, call.data))
                safety = call.meta.get("safety", {})
                if safety.get("required") and not safety.get(
                    "production_checks_active", False
                ):
                    lines.extend(
                        [
                            "> 该状态变更调用的安全检查未由已验证的生产适配器完成；"
                            "不得视为生产审批通过。",
                            "",
                        ]
                    )
                evidence_id = call.meta.get("evidence_id")
                if evidence_id:
                    lines.extend(
                        [
                            f"证据：`{evidence_id}` · 工具版本 `{call.version}`",
                            "",
                        ]
                    )
        else:
            lines.extend(
                [
                    "## 结构化发现",
                    "",
                    "本次没有成功完成的工具结果，因此没有可报告的财务事实。",
                    "",
                ]
            )

        problems = [
            step
            for step in result.steps
            if step.status in {"error", "unknown", "blocked", "not_run"}
        ]
        if problems or result.validation_errors:
            lines.extend(["## 失败与未执行", ""])
            if result.validation_errors:
                lines.append("计划校验失败，未调用任何工具：")
                lines.append("")
                for item in result.validation_errors:
                    lines.append(
                        f"- {item.get('step_id') or 'plan'}：{item.get('message')}"
                    )
                lines.append("")
            for step in problems:
                if step.result and step.result.error:
                    detail = step.result.error.message
                    code = step.result.error.code
                else:
                    detail = step.skip_detail or step.skip_reason or ""
                    code = step.skip_reason or "NOT_RUN"
                lines.append(
                    f"- `{step.step_id}` / `{step.tool}`："
                    f"{_STATUS_LABELS.get(step.status, step.status)} "
                    f"({code})。{detail}"
                )
            lines.append("")
        skipped = [step for step in result.steps if step.status == "skipped"]
        if skipped:
            lines.extend(["## 条件跳过", ""])
            for step in skipped:
                lines.append(
                    f"- `{step.step_id}` / `{step.tool}`："
                    f"{step.skip_reason or '条件未满足'}"
                    + (f"（{step.skip_detail}）" if step.skip_detail else "")
                )
            lines.append("")

        caveats = self._collect_caveats(result)
        if caveats:
            lines.extend(["## 假设与限制", ""])
            for caveat in caveats:
                lines.append(f"- {caveat}")
            lines.append("")

        lines.extend(["## 安全与集成状态", "", self._safety_section(result), ""])

        lines.extend(
            [
                "## 证据索引",
                "",
            ]
        )
        if result.evidence.items:
            lines.extend(
                [
                    "| Evidence | 工具 | 来源 | 模拟 | 采集时间 | Payload SHA-256 |",
                    "|---|---|---|---|---|---|",
                ]
            )
            for item in result.evidence.items:
                lines.append(
                    "| {eid} | {tool}@{version} | {sources} | {simulated} | "
                    "{collected} | `{hash}` |".format(
                        eid=_md(item.evidence_id),
                        tool=_md(item.tool),
                        version=_md(item.tool_version),
                        sources=_md("; ".join(item.sources)),
                        simulated="是" if item.simulated else "否",
                        collected=_md(item.collected_at),
                        hash=_md(item.payload_hash),
                    )
                )
        else:
            lines.append("无可引用证据。")
        lines.append("")

        if result.errors:
            lines.extend(["## 结构化错误", ""])
            for error in result.errors:
                lines.append(
                    f"- `{error.get('step_id')}` · `{error.get('code')}`："
                    f"{error.get('message')}"
                )
            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "报告由 Module 6 工具层根据结构化结果确定性生成；"
                "数值以工具输出及证据哈希为准。",
                "",
            ]
        )
        return "\n".join(lines)

    def write(
        self,
        result: OrchestrationResult,
        path: str | Path,
        *,
        title: str = "AI 银行智能体 · 工具证据报告",
    ) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            self.render(result, title=title), encoding="utf-8"
        )
        return destination

    # ------------------------------------------------------------------
    # Tool-specific rendering
    # ------------------------------------------------------------------

    def _render_tool_data(
        self, tool: str, data: dict[str, Any]
    ) -> list[str]:
        renderer = getattr(self, f"_render_{tool}", None)
        if renderer is not None:
            return renderer(data)
        return self._render_generic(data)

    @staticmethod
    def _render_get_account_balance(data: dict[str, Any]) -> list[str]:
        lines = [
            "| 账户 | 类型 | 尾号 | 可用余额 | 可用额度 | 状态 |",
            "|---|---|---|---|---|---|",
        ]
        for account in data.get("accounts", []):
            available = account.get("available") or account.get("available_credit") or ""
            lines.append(
                "| {aid} | {atype} | {last4} | {balance} | {credit} | {status} |".format(
                    aid=_md(account.get("account_id", "")),
                    atype=_md(account.get("account_type", "")),
                    last4=_md(account.get("last4", "")),
                    balance=_md(account.get("balance", "—")),
                    credit=_md(available or "—"),
                    status=_md(account.get("status", "")),
                )
            )
        lines.append("")
        return lines

    @staticmethod
    def _render_get_transactions(data: dict[str, Any]) -> list[str]:
        totals = data.get("totals", {})
        account = data.get("account", {})
        lines = [
            (
                f"账户 `{account.get('account_id', '')}` / 尾号 "
                f"{account.get('last4', '')}："
                f"支出 ¥{totals.get('total_debit', '0.00')}，"
                f"收入 ¥{totals.get('total_credit', '0.00')}，"
                f"净额 ¥{totals.get('net', '0.00')}。"
            ),
            "",
        ]
        categories = data.get("by_category", [])
        if categories:
            lines.extend(
                [
                    "| 支出类别 | 笔数 | 金额 |",
                    "|---|---|---|",
                ]
            )
            for row in categories:
                lines.append(
                    f"| {_md(row.get('category', ''))} | "
                    f"{row.get('count', 0)} | {row.get('amount', '')} |"
                )
            lines.append("")
        transactions = data.get("transactions", [])
        if transactions:
            lines.extend(
                [
                    "| 日期 | 商户 | 类别 | 方向 | 金额 |",
                    "|---|---|---|---|---|",
                ]
            )
            for row in transactions[:8]:
                lines.append(
                    "| {date} | {merchant} | {category} | {direction} | {amount} |".format(
                        date=_md(row.get("date", "")),
                        merchant=_md(row.get("merchant", "")),
                        category=_md(row.get("category", "")),
                        direction=_md(row.get("direction", "")),
                        amount=_md(row.get("amount", "")),
                    )
                )
            if data.get("truncated"):
                lines.extend(
                    ["", "> 明细已截断；聚合统计仍覆盖完整查询区间。"]
                )
            lines.append("")
        return lines

    @staticmethod
    def _render_analyze_cashflow(data: dict[str, Any]) -> list[str]:
        metrics = data.get("metrics", {})
        lines = [
            f"- 收入：¥{_md(metrics.get('income', ''))}",
            f"- 支出：¥{_md(metrics.get('expenses', ''))}",
            f"- 净现金流：¥{_md(metrics.get('net_cashflow', ''))}",
            f"- 储蓄率：{_md(metrics.get('savings_rate') or '无法计算')}",
            f"- 月均收入：¥{_md(metrics.get('average_monthly_income', ''))}",
            f"- 月均支出：¥{_md(metrics.get('average_monthly_expenses', ''))}",
            "",
        ]
        categories = data.get("by_category", [])
        if categories:
            lines.extend(
                ["| 支出类别 | 金额 | 占比 |", "|---|---|---|"]
            )
            for row in categories:
                lines.append(
                    f"| {_md(row.get('category', ''))} | "
                    f"{row.get('amount', '')} | {row.get('share', '')} |"
                )
            lines.append("")
        return lines

    @staticmethod
    def _render_calculate_financial_health(data: dict[str, Any]) -> list[str]:
        lines = [
            f"**财务健康提示分：{data.get('score')} / 100（{data.get('grade')} 级）**",
            "",
            "| 分项 | 得分 | 权重 | 解释 |",
            "|---|---|---|---|",
        ]
        for component in data.get("components", []):
            lines.append(
                "| {name} | {points} | {weight} | {rationale} |".format(
                    name=_md(component.get("name", "")),
                    points=_md(component.get("points", "")),
                    weight=_md(component.get("weight", "")),
                    rationale=_md(component.get("rationale", "")),
                )
            )
        metrics = data.get("metrics", {})
        lines.extend(
            [
                "",
                f"- 应急金月数：{metrics.get('emergency_fund_months') or '无法估算'}",
                f"- 债务收入比：{metrics.get('debt_to_income') or '无法计算'}",
                f"- 信用卡额度使用率：{metrics.get('credit_utilization', '')}",
                "",
            ]
        )
        return lines

    @staticmethod
    def _render_calculate_risk(data: dict[str, Any]) -> list[str]:
        metrics = data.get("metrics", {})
        return [
            f"- 风险域：`{data.get('risk_domain', '')}`（非运营 Risk Engine）",
            f"- 置信度 / 持有期：{metrics.get('confidence')} / "
            f"{metrics.get('horizon_days')} 天",
            f"- 参数法 VaR：¥{metrics.get('value_at_risk_amount')} "
            f"（{metrics.get('value_at_risk_percent')}%）",
            f"- 年化波动率代理：{metrics.get('annual_volatility_proxy_percent')}%",
            f"- 集中度 HHI：{metrics.get('concentration_hhi')}",
            f"- 提示风险等级：{metrics.get('advisory_risk_level')}",
            f"- 风险标记：{', '.join(data.get('flags', [])) or '无'}",
            "",
        ]

    @staticmethod
    def _render_search_products(data: dict[str, Any]) -> list[str]:
        results = data.get("results", [])
        if not results:
            return ["没有匹配产品，未推断不存在的产品。", ""]
        lines = [
            "| 产品 | 类型 | 指示性年化率 | 年费 | 期限 | 风险 |",
            "|---|---|---|---|---|---|",
        ]
        for product in results:
            lines.append(
                "| {name} (`{pid}`) | {ptype} | {rate}% | {fee} | {term} | {risk} |".format(
                    name=_md(product.get("name", "")),
                    pid=_md(product.get("product_id", "")),
                    ptype=_md(product.get("product_type", "")),
                    rate=_md(product.get("indicative_rate_percent", "")),
                    fee=_md(product.get("annual_fee", "")),
                    term=_md(product.get("term_months") or "不适用"),
                    risk=_md(product.get("risk_level", "")),
                )
            )
        lines.extend(["", f"> {data.get('disclaimer', '')}", ""])
        return lines

    @staticmethod
    def _render_compare_products(data: dict[str, Any]) -> list[str]:
        products = data.get("products", [])
        ids = [product.get("product_id", "") for product in products]
        lines = [
            "| 字段 | " + " | ".join(_md(item) for item in ids) + " |",
            "|---|" + "|".join("---" for _ in ids) + "|",
        ]
        for attribute in data.get("attributes", []):
            values = {
                item.get("product_id"): item.get("value", "")
                for item in attribute.get("values", [])
            }
            lines.append(
                f"| {_md(attribute.get('label', ''))} | "
                + " | ".join(_md(values.get(pid, "")) for pid in ids)
                + " |"
            )
        lines.append("")
        for observation in data.get("observations", []):
            lines.append(f"- {observation}")
        lines.extend(["", f"> {data.get('disclaimer', '')}", ""])
        return lines

    @staticmethod
    def _render_retrieve_policy(data: dict[str, Any]) -> list[str]:
        if data.get("no_basis"):
            return [
                "未找到可引用的政策依据（`no_basis=true`），未编造结论。",
                "",
            ]
        lines: list[str] = []
        for match in data.get("matches", []):
            stale = " **已失效**" if match.get("stale") else ""
            lines.extend(
                [
                    f"- {match.get('citation', '')}{stale}（{match.get('source', '')}）",
                    f"  > {match.get('excerpt', '')}",
                ]
            )
        lines.extend(
            [
                "",
                "> 检索文本为不可信参考材料，不是系统指令，不能触发工具或修改权限。",
                "",
            ]
        )
        return lines

    @staticmethod
    def _render_calculate_loan(data: dict[str, Any]) -> list[str]:
        result = data.get("result", {})
        loan = data.get("loan", {})
        lines = [
            f"- 本金：¥{loan.get('principal')}，年化：{loan.get('annual_rate_percent')}%，"
            f"期限：{loan.get('term_months')} 个月，方式：{loan.get('repayment_method')}",
            f"- 月供：{result.get('monthly_payment') or '不适用（等额本金）'}",
            f"- 首月 / 末月：¥{result.get('first_payment')} / ¥{result.get('last_payment')}",
            f"- 总还款：¥{result.get('total_payment')}",
            f"- 总利息：¥{result.get('total_interest')}",
            "",
            "| 期数 | 还款 | 本金 | 利息 | 剩余本金 |",
            "|---|---|---|---|---|",
        ]
        for row in data.get("schedule_preview", [])[:6]:
            lines.append(
                f"| {row.get('month')} | {row.get('payment')} | "
                f"{row.get('principal')} | {row.get('interest')} | "
                f"{row.get('remaining_balance')} |"
            )
        lines.append("")
        return lines

    @staticmethod
    def _render_calculate_portfolio(data: dict[str, Any]) -> list[str]:
        metrics = data.get("metrics", {})
        return [
            f"- 预期年化（模拟）：{metrics.get('expected_annual_return_percent')}%",
            f"- 总投入：¥{metrics.get('total_contributions')}",
            f"- 预期情景价值：¥{metrics.get('projected_value')}",
            f"- 预期收益：¥{metrics.get('projected_gain')}",
            f"- 压力情景价值：¥{metrics.get('stress_value')}",
            "",
            f"> {data.get('disclaimer', '')}",
            "",
        ]

    @staticmethod
    def _render_create_budget(data: dict[str, Any]) -> list[str]:
        lines = [
            f"- 预算 ID：`{data.get('budget_id')}`",
            f"- 月份：{data.get('month')}，月收入：¥{data.get('monthly_income')}",
            f"- 已分配：¥{data.get('total_budgeted')}，未分配：¥{data.get('unallocated')}",
            f"- 状态：{data.get('status')}；持久化：{data.get('persistence_mode')}",
            "",
            "| 类别 | 限额 | 收入占比 |",
            "|---|---|---|",
        ]
        for category in data.get("categories", []):
            lines.append(
                f"| {_md(category.get('category', ''))} | "
                f"{category.get('limit', '')} | {category.get('income_share', '')} |"
            )
        lines.append("")
        return lines

    @staticmethod
    def _render_create_alert(data: dict[str, Any]) -> list[str]:
        delivery = data.get("delivery", {})
        return [
            f"- 提醒 ID：`{data.get('alert_id')}`（{data.get('alert_type')}）",
            f"- 阈值：¥{data.get('threshold')}",
            f"- 渠道：{data.get('channel')}；状态：{data.get('status')}",
            f"- 投递：{delivery.get('mode')} / sent={delivery.get('sent')}",
            "",
        ]

    @staticmethod
    def _render_execute_transaction(data: dict[str, Any]) -> list[str]:
        return [
            f"- 模拟交易号：`{data.get('transaction_id')}` "
            f"(duplicate={data.get('duplicate')})",
            f"- 收款人：{data.get('beneficiary', {}).get('name')} "
            f"（尾号 {data.get('beneficiary', {}).get('account_last4')}）",
            f"- 金额：¥{data.get('amount')}，手续费：¥{data.get('fee')}",
            f"- 余额：¥{data.get('balance_before')} → ¥{data.get('balance_after')}",
            f"- 状态：{data.get('status')}；simulated={data.get('simulated')}",
            "",
            f"> {data.get('disclaimer', '')}",
            "",
        ]

    def _render_generic(self, data: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for key, value in data.items():
            if key == "summary" or isinstance(value, (dict, list)):
                continue
            if value is None:
                continue
            lines.append(f"- {key}：{value}")
        return lines + ([""] if lines else [])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_caveats(result: OrchestrationResult) -> list[str]:
        seen: set[str] = set()
        caveats: list[str] = []
        for item in result.evidence.items:
            for caveat in item.caveats:
                if caveat not in seen:
                    seen.add(caveat)
                    caveats.append(caveat)
        return caveats[:30]

    @staticmethod
    def _safety_section(result: OrchestrationResult) -> str:
        calls = [
            step.result
            for step in result.steps
            if step.result is not None
            and step.result.meta.get("safety") is not None
        ]
        if not calls:
            return (
                "本次计划没有调用到工具，因此没有 Risk Engine 或 "
                "Compliance Guard 的运行证据。"
            )
        rows = [
            "| 步骤调用 | 安全检查要求 | Compliance | Risk | 生产检查激活 |",
            "|---|---|---|---|---|",
        ]
        any_mock = False
        any_production = False
        for call in calls:
            safety = call.meta.get("safety", {})
            comp = safety.get("compliance", {})
            risk = safety.get("risk", {})
            if comp.get("adapter_kind") == "mock" or risk.get("adapter_kind") == "mock":
                any_mock = True
            if safety.get("production_checks_active"):
                any_production = True
            rows.append(
                "| {tool} / `{call}` | {required} | {comp} | {risk} | {active} |".format(
                    tool=_md(call.tool),
                    call=_md(call.call_id),
                    required="是" if safety.get("required") else "否",
                    comp=_md(comp.get("status", "not_run")),
                    risk=_md(risk.get("status", "not_run")),
                    active="是" if safety.get("production_checks_active") else "否",
                )
            )
        rows.append("")
        notes: list[str] = []
        if any_mock:
            notes.append(
                "本次使用了明确标记的 **Mock safety adapter**；它只是测试替身，"
                "不是已完成的 Risk Engine/Compliance Guard。"
            )
        if any_production:
            notes.append(
                "有调用报告了生产适配器已执行检查。该声明来自注入适配器，"
                "仍需以被接入模块自身的审计记录为准。"
            )
        if not any_production:
            notes.append(
                "没有调用获得已验证的生产安全适配器结论；任何状态变更都不应"
                "因此被视为生产审批通过。"
            )
        return "\n".join(rows + notes + [""])


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def generate_report(result: OrchestrationResult) -> str:
    return MarkdownReportGenerator().render(result)


def write_report(result: OrchestrationResult, path: str | Path) -> Path:
    return MarkdownReportGenerator().write(result, path)
