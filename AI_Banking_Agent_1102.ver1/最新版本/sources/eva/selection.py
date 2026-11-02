"""阶段 3：工具选择与参数校验。

在真正调用工具之前完成：
- 工具是否注册；
- 必填参数是否齐全；
- 依赖和 ${step.field} 引用是否指向更早的步骤；
- 当前会话认证强度是否允许执行资金变动类工具。
"""

from __future__ import annotations

import time

from ..models import Plan, Session, ToolSpec, TraceEvent
from ..utils import find_refs

INJECTED_ARGS = {"customer_id", "idempotency_key"}


class SelectionError(Exception):
    pass


def select_tools(
    plan: Plan, registry, session: Session
) -> tuple[list[ToolSpec], TraceEvent]:
    started = time.perf_counter()
    specs: list[ToolSpec] = []

    step_index = {step.step_id: index for index, step in enumerate(plan.steps)}
    if len(step_index) != len(plan.steps):
        raise SelectionError("计划中存在重复的步骤 ID。")

    for step in plan.steps:
        if step.tool not in registry:
            raise SelectionError(f"计划引用了未注册的工具：{step.tool}")

        spec = registry.get(step.tool)
        if spec.mutating != step.mutating:
            raise SelectionError(
                f"步骤 {step.step_id} 的工具变更属性与计划不一致。"
            )
        if step.requires_confirmation and not spec.mutating:
            raise SelectionError(
                f"步骤 {step.step_id} 标记了二次确认，但工具不是资金变动类。"
            )
        if spec.mutating and session.identity_level != "strong":
            raise SelectionError("当前登录认证强度不足，无法执行资金变动类操作。")
        if spec.requires_step_up and session.identity_level != "strong":
            raise SelectionError("当前认证强度不满足 R4 操作要求，请重新认证。")
        missing_scopes = set(spec.scopes) - set(session.scopes)
        if missing_scopes:
            raise SelectionError(
                "当前会话缺少工具所需权限："
                + "、".join(sorted(missing_scopes))
            )

        for argument in spec.required_args:
            if argument in INJECTED_ARGS:
                continue
            if argument not in step.args:
                raise SelectionError(
                    f"工具 {step.tool} 缺少必填参数：{argument}"
                )

        for dependency in step.depends_on:
            if dependency not in step_index:
                raise SelectionError(
                    f"步骤 {step.step_id} 依赖不存在的步骤 {dependency}。"
                )
            if step_index[dependency] >= step_index[step.step_id]:
                raise SelectionError(
                    f"步骤依赖顺序错误：{step.step_id} 依赖 {dependency}。"
                )

        for ref_step, field in find_refs(step.args):
            if ref_step not in step_index:
                raise SelectionError(
                    f"步骤 {step.step_id} 引用了不存在的步骤 {ref_step}.{field}。"
                )
            if step_index[ref_step] >= step_index[step.step_id]:
                raise SelectionError(
                    f"参数引用必须指向更早的步骤：{step.step_id} -> {ref_step}.{field}。"
                )

        specs.append(spec)

    elapsed = (time.perf_counter() - started) * 1000
    event = TraceEvent(
        stage="tool_selection",
        ok=True,
        summary=f"{len(specs)} 个工具通过选择与参数校验",
        detail={
            "tools": [
                {
                    "tool": spec.name,
                    "mutating": spec.mutating,
                    "risk_tier": spec.risk_tier,
                    "version": spec.version,
                    "scopes": list(spec.scopes),
                    "required_args": list(spec.required_args),
                }
                for spec in specs
            ]
        },
        elapsed_ms=round(elapsed, 2),
    )
    return specs, event
