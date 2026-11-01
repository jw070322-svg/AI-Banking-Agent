"""总控：把各阶段串成一条可审计、可中断、可恢复的流水线。

    用户输入 -> 合规扫描 -> 意图识别 -> 任务规划 -> 工具选择
             -> 风控校验/预览/确认 -> 工具执行（可暂停）
             -> 结果校验 -> 回复生成 -> Action Log
"""

from __future__ import annotations

import re

from .brain import RuleBasedBrain, merge_intents
from .data import MockBank
from .models import (
    CONTROLLED_REJECTION_CODES,
    STATUS_LABELS,
    AgentResponse,
    Intent,
    PendingAction,
    Plan,
    Session,
    Status,
    ToolResult,
    TraceEvent,
    new_id,
    utc_now,
)
from .risk import RiskComplianceEngine
from .risk.models import Approval, RiskAssessment, RiskControlError
from .stages.execution import execute_plan
from .stages.intent import recognize_intent
from .stages.planning import PlanningError, build_plan
from .stages.response import compose_response
from .stages.selection import SelectionError, select_tools
from .stages.verification import verify_results
from .tools import ToolRegistry
from .utils import jsonable

CONFIRM_PHRASES = {
    "确认",
    "确定",
    "是",
    "好",
    "好的",
    "可以",
    "执行",
    "同意",
    "确认执行",
    "确认转账",
    "确认冻结",
    "yes",
    "y",
    "ok",
    "okay",
}

CANCEL_PHRASES = {
    "取消",
    "不",
    "否",
    "不要",
    "不用",
    "算了",
    "取消操作",
    "不转了",
    "不冻了",
    "no",
    "n",
}


def classify_confirmation(text: str) -> str | None:
    cleaned = re.sub(r"[\s，。,.！!？?]", "", text.lower())
    if cleaned in CONFIRM_PHRASES:
        return "confirm"
    if cleaned in CANCEL_PHRASES:
        return "cancel"
    if len(cleaned) <= 4:
        if any(word in cleaned for word in ("确认", "确定", "同意", "执行")):
            return "confirm"
        if any(word in cleaned for word in ("取消", "不要", "算了", "不办")):
            return "cancel"
    return None


class BankingAgent:
    def __init__(
        self,
        bank: MockBank | None = None,
        brain: RuleBasedBrain | None = None,
        registry: ToolRegistry | None = None,
        risk_engine: RiskComplianceEngine | None = None,
        action_log_root: str = "logs",
        preview_state_path: str | None = None,
    ):
        self.bank = bank or MockBank()
        self.registry = registry or ToolRegistry(self.bank)
        self.brain = brain or RuleBasedBrain()
        self.risk = risk_engine or RiskComplianceEngine(
            self.bank,
            registry=self.registry,
            log_dir=action_log_root,
            preview_state_path=preview_state_path,
        )
        redactor = getattr(self.risk, "redact_payload", None)
        if redactor is not None:
            self.bank.audit_redactor = redactor

    def new_session(self, customer_id: str = "CUST-001") -> Session:
        customer = self.bank.customers.get(customer_id)
        identity_level = customer["identity_level"] if customer else "strong"
        return Session(
            session_id=new_id("SESS"),
            customer_id=customer_id,
            identity_level=identity_level,
        )

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def handle(self, session: Session, text: str) -> AgentResponse:
        audit_id = new_id("AUD")
        text = (text or "").strip()
        trace: list[TraceEvent] = [
            TraceEvent(
                stage="user_input",
                ok=True,
                summary="收到用户请求",
                detail={"text": text},
            )
        ]

        if not text:
            return self._handle_empty_input(session, audit_id, trace)

        # 阶段 0：合规扫描（提示注入 / PII），只做确定性规则判断。
        compliance = self.risk.scan_input(text)
        trace.append(self.risk.compliance_event(compliance))
        # trace 也不保留完整 PII。
        trace[0].detail["text"] = self.risk.redact_text(text)

        # 上一轮有等待确认的资金变动操作
        if session.pending:
            decision = classify_confirmation(text)
            if decision == "confirm":
                return self._resume(session, audit_id, trace)
            if decision == "cancel":
                return self._cancel(session, audit_id, trace)

            abandoned = session.pending
            session.pending = None
            self.risk.abandon(abandoned.risk_state, session)
            trace.append(
                TraceEvent(
                    stage="user_input",
                    ok=True,
                    summary="检测到新的请求，已放弃上一轮待确认操作",
                    detail={"plan_id": abandoned.plan.plan_id},
                )
            )
            self.bank.record_audit(
                {
                    "event": "pending_plan_abandoned",
                    "session_id": session.session_id,
                    "customer_id": session.customer_id,
                    "plan_id": abandoned.plan.plan_id,
                }
            )

        # 上一轮有等待补充的信息
        clarification = session.pending_clarification
        if clarification and classify_confirmation(text) == "cancel":
            session.pending_clarification = None
            trace.append(
                TraceEvent(
                    stage="intent",
                    ok=True,
                    summary="用户取消待补充的业务办理",
                    detail={"slots": jsonable(clarification.slots)},
                )
            )
            text_out = compose_response(
                Status.CANCELLED.value, clarification, None, [], None, audit_id
            )
            trace.append(self._response_event(Status.CANCELLED.value))
            return self._finalize(
                session,
                audit_id,
                Status.CANCELLED.value,
                text_out,
                clarification,
                None,
                [],
                None,
                trace,
                text,
            )

        # 阶段 1：意图识别
        intent, intent_event = recognize_intent(session, text, self.brain)
        trace.append(intent_event)

        # 多轮补槽：把本轮信息合并进上一轮未完成的意图
        if clarification:
            if intent.name in (clarification.name, "unknown"):
                supplement = self.brain.extract_slots(text, clarification.name)
                merged = merge_intents(
                    clarification,
                    Intent(
                        name=clarification.name,
                        confidence=0.90,
                        slots=supplement,
                        risk=clarification.risk,
                        rationale="用户补充信息",
                    ),
                )
                session.pending_clarification = None
                trace.append(
                    TraceEvent(
                        stage="intent",
                        ok=True,
                        summary=(
                            "已合并用户补充的信息"
                            if not merged.missing_slots
                            else "已补充信息，仍需等待缺失槽位"
                        ),
                        detail={
                            "slots": jsonable(merged.slots),
                            "missing_slots": merged.missing_slots,
                        },
                    )
                )
                if merged.missing_slots:
                    session.pending_clarification = merged
                    text_out = compose_response(
                        Status.NEEDS_INPUT.value, merged, None, [], None, audit_id
                    )
                    trace.append(self._response_event(Status.NEEDS_INPUT.value))
                    return self._finalize(
                        session,
                        audit_id,
                        Status.NEEDS_INPUT.value,
                        text_out,
                        merged,
                        None,
                        [],
                        None,
                        trace,
                        text,
                    )
                intent = merged
            else:
                session.pending_clarification = None
                trace.append(
                    TraceEvent(
                        stage="intent",
                        ok=True,
                        summary="用户切换到新的业务，已放弃上一轮待补充信息",
                    )
                )

        # 能力边界
        if intent.name == "unknown" or intent.confidence < 0.45:
            trace.append(
                TraceEvent(
                    stage="response",
                    ok=True,
                    summary="超出当前能力范围，未生成计划",
                )
            )
            text_out = compose_response(
                Status.UNSUPPORTED.value, intent, None, [], None, audit_id
            )
            return self._finalize(
                session,
                audit_id,
                Status.UNSUPPORTED.value,
                text_out,
                intent,
                None,
                [],
                None,
                trace,
                text,
            )

        # 缺少槽位：保存上下文，等待用户补充
        if intent.missing_slots:
            session.pending_clarification = intent
            text_out = compose_response(
                Status.NEEDS_INPUT.value, intent, None, [], None, audit_id
            )
            trace.append(self._response_event(Status.NEEDS_INPUT.value))
            return self._finalize(
                session,
                audit_id,
                Status.NEEDS_INPUT.value,
                text_out,
                intent,
                None,
                [],
                None,
                trace,
                text,
            )

        # 阶段 2：任务规划
        try:
            plan, plan_event = build_plan(intent, session)
        except PlanningError as exc:
            trace.append(
                TraceEvent(stage="plan", ok=False, summary=f"规划失败：{exc}")
            )
            text_out = f"无法生成执行计划：{exc}"
            trace.append(self._response_event(Status.FAILED.value))
            return self._finalize(
                session,
                audit_id,
                Status.FAILED.value,
                text_out,
                intent,
                None,
                [],
                None,
                trace,
                text,
            )
        trace.append(plan_event)

        # 阶段 3：工具选择
        try:
            _, selection_event = select_tools(plan, self.registry, session)
        except SelectionError as exc:
            trace.append(
                TraceEvent(
                    stage="tool_selection",
                    ok=False,
                    summary=f"工具选择失败：{exc}",
                )
            )
            text_out = f"无法执行该请求：{exc}"
            trace.append(self._response_event(Status.FAILED.value))
            return self._finalize(
                session,
                audit_id,
                Status.FAILED.value,
                text_out,
                intent,
                plan,
                [],
                None,
                trace,
                text,
            )
        trace.append(selection_event)

        # 阶段 3.5：Risk & Compliance 评估
        # 策略拒绝 / 提示注入在这里 fail closed；R3/R4 通过后生成服务端预览。
        assessment = self.risk.assess(plan, session, text, compliance=compliance)
        trace.append(self.risk.assessment_event(assessment))
        if assessment.blocked:
            return self._blocked_response(
                session,
                audit_id,
                trace,
                intent,
                plan,
                assessment,
                user_text=text,
            )

        # 阶段 4：工具执行（可能暂停等待确认）
        outcome = execute_plan(plan, self.registry, session)
        trace.extend(outcome.events)

        if outcome.paused_index is not None:
            session.pending = PendingAction(
                plan=plan,
                results=outcome.results,
                next_step_index=outcome.paused_index,
                trace_prefix=list(trace),
                risk_state=assessment,
            )
            text_out = compose_response(
                Status.NEEDS_CONFIRMATION.value,
                intent,
                plan,
                outcome.results,
                None,
                audit_id,
            )
            preview_decision = next(
                (
                    decision
                    for decision in assessment.decisions
                    if decision.preview is not None
                ),
                None,
            )
            if preview_decision is not None:
                text_out += (
                    f"\n• 风控等级：{preview_decision.tier}"
                    f"（{preview_decision.operation}），"
                    f"预览号 {preview_decision.preview.preview_id}"
                    f"（{preview_decision.preview.expires_at} 前有效）"
                )
            trace.append(self._response_event(Status.NEEDS_CONFIRMATION.value))
            return self._finalize(
                session,
                audit_id,
                Status.NEEDS_CONFIRMATION.value,
                text_out,
                intent,
                plan,
                outcome.results,
                None,
                trace,
                text,
                assessment=assessment,
            )

        # 阶段 5：结果校验
        report, verification_event = verify_results(
            plan, outcome.results, self.bank, session
        )
        trace.append(verification_event)

        # 阶段 6：回复生成
        status = self._resolve_status(outcome, report)
        text_out = compose_response(
            status, intent, plan, outcome.results, report, audit_id
        )
        trace.append(self._response_event(status))
        return self._finalize(
            session,
            audit_id,
            status,
            text_out,
            intent,
            plan,
            outcome.results,
            report,
            trace,
            text,
            assessment=assessment,
        )

    # ------------------------------------------------------------------
    # 确认 / 恢复 / 取消
    # ------------------------------------------------------------------

    def _resume(
        self, session: Session, audit_id: str, trace: list[TraceEvent]
    ) -> AgentResponse:
        pending = session.pending
        assert pending is not None
        session.pending = None

        trace[0].summary = "用户确认执行挂起操作"
        full_trace = [*pending.trace_prefix, *trace]

        approvals: dict[str, Approval] = {}
        try:
            approvals = self.risk.confirm(
                pending.risk_state, session, decision="approved"
            )
        except RiskControlError as exc:
            full_trace.append(
                TraceEvent(
                    stage="approval",
                    ok=False,
                    summary=f"确认失败：{exc.message}",
                    detail={"error_code": exc.code},
                )
            )
            return self._blocked_response(
                session,
                audit_id,
                full_trace,
                pending.plan.intent,
                pending.plan,
                pending.risk_state,
                error_code=exc.code,
                reason=exc.message,
                user_text="确认",
            )
        full_trace.append(self.risk.approval_event(approvals))

        outcome = execute_plan(
            pending.plan,
            self.registry,
            session,
            prior_results=pending.results,
            start_index=pending.next_step_index,
            approved=True,
            authorize=lambda step, resolved: self.risk.authorize_step(
                step,
                resolved,
                session,
                pending.risk_state,
                approvals,
            ),
        )
        full_trace.extend(outcome.events)

        report, verification_event = verify_results(
            pending.plan, outcome.results, self.bank, session
        )
        full_trace.append(verification_event)

        status = self._resolve_status(outcome, report)
        text_out = compose_response(
            status,
            pending.plan.intent,
            pending.plan,
            outcome.results,
            report,
            audit_id,
        )
        full_trace.append(self._response_event(status))
        return self._finalize(
            session,
            audit_id,
            status,
            text_out,
            pending.plan.intent,
            pending.plan,
            outcome.results,
            report,
            full_trace,
            "确认",
            assessment=pending.risk_state,
            approvals=approvals,
        )

    def _cancel(
        self, session: Session, audit_id: str, trace: list[TraceEvent]
    ) -> AgentResponse:
        pending = session.pending
        assert pending is not None
        session.pending = None

        trace[0].summary = "用户取消挂起操作"
        full_trace = [*pending.trace_prefix, *trace]

        approvals: dict[str, Approval] = {}
        try:
            approvals = self.risk.confirm(
                pending.risk_state, session, decision="denied"
            )
        except RiskControlError:
            approvals = {}

        full_trace.append(
            TraceEvent(
                stage="response",
                ok=True,
                summary="用户取消，未执行资金变动",
            )
        )
        text_out = compose_response(
            Status.CANCELLED.value,
            pending.plan.intent,
            pending.plan,
            pending.results,
            None,
            audit_id,
        )
        return self._finalize(
            session,
            audit_id,
            Status.CANCELLED.value,
            text_out,
            pending.plan.intent,
            pending.plan,
            pending.results,
            None,
            full_trace,
            "取消",
            assessment=pending.risk_state,
            approvals=approvals,
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _blocked_response(
        self,
        session: Session,
        audit_id: str,
        trace: list[TraceEvent],
        intent: Intent | None,
        plan: Plan | None,
        assessment: RiskAssessment | None,
        error_code: str | None = None,
        reason: str | None = None,
        user_text: str = "",
    ) -> AgentResponse:
        """风控/合规拒绝：不执行任何工具，构造受控拒绝结果并写日志。"""
        decision = None
        if assessment is not None:
            decision = assessment.first_blocked()
            if decision is None:
                mutation_decisions = assessment.mutation_decisions()
                decision = mutation_decisions[0] if mutation_decisions else None

        code = (
            error_code
            or (decision.error_code if decision else None)
            or "POLICY_DENIED"
        )
        message = reason or (
            decision.reason if decision else "请求未通过风控校验。"
        )
        step_id = (
            decision.step_id
            if decision
            else (plan.steps[-1].step_id if plan and plan.steps else "risk")
        )
        tool = decision.tool if decision else "orchestrator.risk_gate"
        result = ToolResult(
            step_id=step_id,
            tool=tool,
            ok=False,
            data={"reasons": [message]},
            error=message,
            error_code=code,
        )
        results = [result]

        report = None
        if plan is not None:
            report, verification_event = verify_results(
                plan, results, self.bank, session
            )
            trace.append(verification_event)

        status = Status.REJECTED.value
        text_out = compose_response(status, intent, plan, results, report, audit_id)
        trace.append(self._response_event(status))
        return self._finalize(
            session,
            audit_id,
            status,
            text_out,
            intent,
            plan,
            results,
            report,
            trace,
            user_text,
            assessment=assessment,
        )

    def _handle_empty_input(
        self, session: Session, audit_id: str, trace: list[TraceEvent]
    ) -> AgentResponse:
        if session.pending:
            intent = session.pending.plan.intent
            plan = session.pending.plan
            results = session.pending.results
            status = Status.NEEDS_CONFIRMATION.value
            text_out = "请回复「确认」执行，或回复「取消」。"
        elif session.pending_clarification:
            intent = session.pending_clarification
            plan = None
            results = []
            status = Status.NEEDS_INPUT.value
            text_out = compose_response(
                status, intent, None, [], None, audit_id
            )
        else:
            intent = None
            plan = None
            results = []
            status = Status.NEEDS_INPUT.value
            text_out = "请输入您想办理的业务。"

        trace.append(self._response_event(status))
        return self._finalize(
            session,
            audit_id,
            status,
            text_out,
            intent,
            plan,
            results,
            None,
            trace,
            "",
        )

    def _resolve_status(self, outcome, report) -> str:
        if outcome.fatal_error:
            failed = [result for result in outcome.results if not result.ok]
            if failed and all(
                result.error_code in CONTROLLED_REJECTION_CODES
                for result in failed
            ):
                return Status.REJECTED.value
            return Status.FAILED.value
        if not report or not report.passed:
            return Status.FAILED.value
        return Status.COMPLETED.value

    def _response_event(self, status: str) -> TraceEvent:
        return TraceEvent(
            stage="response",
            ok=status != Status.FAILED.value,
            summary=f"回复用户：{STATUS_LABELS.get(status, status)}",
        )

    def _finalize(
        self,
        session: Session,
        audit_id: str,
        status: str,
        text: str,
        intent: Intent | None,
        plan: Plan | None,
        results,
        report,
        trace: list[TraceEvent],
        user_text: str,
        assessment: RiskAssessment | None = None,
        approvals: dict[str, Approval] | None = None,
    ) -> AgentResponse:
        # 合规：回复文本也不能包含完整账号/手机号/身份证号。
        text = self.risk.redact_text(text)
        # trace 与应用内历史不是业务返回体，统一脱敏 PII 和完整户名。
        for event in trace:
            event.detail = self.risk.redact_payload(event.detail)
            event.summary = self.risk.redact_payload(event.summary)

        mutating_step_ids = (
            {step.step_id for step in plan.steps if step.mutating} if plan else set()
        )
        requires_review = (
            status == Status.FAILED.value
            and any(
                result.ok and result.step_id in mutating_step_ids
                for result in results
            )
        ) or bool(assessment and assessment.requires_review)

        session.history.append(
            {
                "user": self.risk.redact_payload(user_text),
                "assistant": self.risk.redact_payload(text),
                "status": status,
                "at": utc_now(),
            }
        )
        self.bank.record_audit(
            {
                "audit_id": audit_id,
                "event": "agent_turn",
                "session_id": session.session_id,
                "customer_id": session.customer_id,
                "status": status,
                "intent": intent.name if intent else None,
                "plan_id": plan.plan_id if plan else None,
                "tools": [result.tool for result in results],
                "verification_passed": report.passed if report else None,
                "requires_review": requires_review,
                "policy_version": self.risk.policy.version,
                "risk_blocked": bool(assessment and assessment.blocked),
                "risk_tiers": (
                    {
                        decision.step_id: decision.tier
                        for decision in assessment.decisions
                    }
                    if assessment
                    else {}
                ),
            }
        )
        self.risk.record_turn(
            session=session,
            intent=intent,
            plan=plan,
            results=results,
            report=report,
            status=status,
            user_text=user_text,
            audit_id=audit_id,
            assessment=assessment,
            approvals=approvals,
            requires_review=requires_review,
        )
        return AgentResponse(
            status=status,
            text=text,
            audit_id=audit_id,
            intent=intent,
            plan=plan,
            results=results,
            verification=report,
            trace=trace,
            risk=assessment,
        )
