"""只读观测会话 CLI：prepare / record / finish 三段式。

为什么是三段式：浏览器动作由浏览器技能侧执行（每步真实观测 + 证据落盘），
本 CLI 负责契约与状态机——prepare 生成步骤与定位符候选；record 校验每步结果
（Schema + 证据文件与哈希 + 状态断言）并给出唯一裁决（CONTINUE/RETRY/
WAITING_USER/ABORT）；finish 生成汇总。裁决来自代码，不来自现场发挥。

用法：
  python -m executor.run_session prepare --customer-ref "example_customer.json(synthetic)" \
      --city 杭州 --keyword 生日餐厅
  python -m executor.run_session record --session-dir <dir> --step-file <json>
  python -m executor.run_session finish --session-dir <dir> --outcome completed|aborted|waiting_user --note "..."
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from executor.base import (GOAL_BLOCKED, GOAL_FAILED, GOAL_PARTIAL, GOAL_SATISFIED,  # noqa: E402
                           STATUS_FAILED, STATUS_OK, STATUS_SKIPPED,
                           STATUS_WAITING_USER, ExecutionLog, detect_waiting_user,
                           needs_retry, new_session_dir, sha256_of, verify_state)
from executor.locator_registry import default_registry  # noqa: E402
from executor.readonly_actions import build_step  # noqa: E402
from workflow import now  # noqa: E402

VERDICTS = ("CONTINUE", "RETRY", "WAITING_USER", "ABORT")


def _canonical_hash(payload):
    return sha256_of_bytes(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def sha256_of_bytes(data):
    import hashlib
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_goal_outcome(steps, planned=None):
    """目标裁决（S1.2 修复 R1）：必要性与后置条件**只从计划**推导，
    recorded 步骤自报的 required_for_goal 不再采信。

    - 终局尝试：每 step_id 取最大 attempt 的记录决定该步骤状态；
      失败后重试成功按终局尝试计一次目标（早期尝试标 superseded 语义）
    - 计划中必要但从未记录的步骤按 not_executed 处理 → blocked
      （防止"计划了四步只记录两步成功"被当成全链成功）
    - 任一必要步骤终局 failed → failed
    - 任一必要步骤终局 waiting_user / skipped / not_executed → blocked
    - 全部必要步骤终局 ok（≥1 条）→ satisfied
    - 计划未绑定必要步骤 → partial（无法宣称满足，也不算失败）"""
    plan_required = {}
    for planned_action, planned_step in (planned or {}).items():
        if planned_step.get("required_for_goal", True):
            plan_required[planned_action] = planned_step
    terminal = {}
    for s in steps:
        action = s.get("action")
        current = terminal.get(action)
        if current is None or (s.get("attempt") or 0) > (current.get("attempt") or 0):
            terminal[action] = s
    if not plan_required:
        return GOAL_PARTIAL
    statuses = [terminal[action].get("status") if action in terminal else "not_executed"
                for action in plan_required]
    if any(s == STATUS_FAILED for s in statuses):
        return GOAL_FAILED
    if any(s in (STATUS_WAITING_USER, STATUS_SKIPPED, "not_executed") for s in statuses):
        return GOAL_BLOCKED
    if all(s == STATUS_OK for s in statuses):
        return GOAL_SATISFIED
    return GOAL_BLOCKED


def cmd_prepare(args):
    base = Path(args.base) if args.base else Path(__file__).parent.parent / "reports" / "sessions"
    session = new_session_dir(base)
    log = ExecutionLog(session)
    header = log.run_start(args.customer_ref)
    steps = [
        build_step("open_site", {"url": "https://www.dianping.com/"}, 1),
        build_step("select_city", {"city_name": args.city}, 2),
        build_step("resolve_location", {"mode": "city_only", "target_city": args.city}, 3),
        build_step("search", {"public_keyword": args.keyword, "target_city": args.city}, 4),
    ]
    registry = default_registry()
    plan_hash = sha256_of_bytes(json.dumps(steps, sort_keys=True, ensure_ascii=False))
    plan = {"session_dir": str(session), "run_id": header["run_id"],
            "created_at": now(), "customer_ref": args.customer_ref,
            "timeout_seconds": 30, "steps": steps, "plan_hash": plan_hash,
            "locator_hints": registry.to_json()}
    (session / "steps.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    (session / "locator_snapshot.json").write_text(registry.to_json(), encoding="utf-8")
    print(json.dumps({"session_dir": str(session), "run_id": header["run_id"],
                      "steps": [s["action"] for s in steps]}, ensure_ascii=False))
    return 0


def decide(step_result, registry_observations=None):
    """唯一裁决点：证据之外的一切判定都在这里（可单测）。"""
    status = step_result.get("status")
    if status == STATUS_SKIPPED:
        return "CONTINUE", (step_result.get("response_summary")
                            or "只读跳过（city_only 无页面操作）")
    if status == STATUS_WAITING_USER:
        return "WAITING_USER", step_result.get("response_summary") or "页面要求人工接管"
    if status == STATUS_OK:
        expected = step_result.get("postconditions") or {}
        observed = step_result.get("observed_state") or {}
        ok, message = verify_state(expected, observed)
        if not ok:
            return "ABORT", message
        wall = detect_waiting_user(observed.get("state_summary", ""))
        if wall:
            return "WAITING_USER", wall
        return "CONTINUE", "状态核验一致"
    # failed
    retries = int(step_result.get("retries") or 0)
    if needs_retry(step_result.get("action"), STATUS_FAILED, retries):
        return "RETRY", "只读动作允许再试一次"
    return "ABORT", step_result.get("error_code") or "动作失败且重试已用尽"


def cmd_record(args):
    session = Path(args.session_dir)
    step_result = json.loads(Path(args.step_file).read_text(encoding="utf-8-sig"))
    log = ExecutionLog(session)
    lines = log.load_lines()
    # 终局保护（S1.2 R1）：会话已 finalize 后拒绝任何步骤写入
    if any(line.get("type") == "session_end" for line in lines):
        raise ValueError("会话已 finalize（session_end 存在）；拒绝记录后续步骤")
    # 计划冻结对账（S1.2 R1）：plan_hash 必须一致；步骤必须按计划 step_id 执行
    plan_path = session / "steps.json"
    if not plan_path.is_file():
        raise ValueError("会话缺少 steps.json 计划文件；拒绝记录（计划冻结）")
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    if plan.get("plan_hash") != _canonical_hash(plan.get("steps", [])):
        raise ValueError("计划文件被篡改（plan_hash 不一致）；拒绝记录")
    plan_steps = {s["step_id"]: s for s in plan.get("steps", [])}
    step_id = step_result.get("step_id")
    attempt = step_result.get("attempt")
    if not step_id or step_id not in plan_steps:
        raise ValueError(f"step_id 缺失或不在计划中：{step_id!r}；步骤必须按计划执行")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("attempt 必须为 ≥1 整数")
    plan_step = plan_steps[step_id]
    if step_result.get("action") != plan_step["action"]:
        raise ValueError(f"step_id {step_id} 对应计划动作 {plan_step['action']!r}，"
                         f"收到 {step_result.get('action')!r}")
    # 必要性从计划推导：自报 required_for_goal 与计划不符即拒绝（篡改可见）
    if "required_for_goal" in step_result and \
            step_result["required_for_goal"] != plan_step.get("required_for_goal", True):
        raise ValueError(f"step_id {step_id} 的 required_for_goal 与计划契约不符；拒绝（R1）")
    # 后置条件来源=计划契约：自报不一致即拒绝
    plan_postconditions = plan_step.get("postconditions") or {}
    if "postconditions" in step_result and \
            step_result["postconditions"] != plan_postconditions:
        raise ValueError(f"step_id {step_id} 的 postconditions 与计划契约不符；拒绝（R1）")
    # 尝试序号单调递增：重试显式建模（终局尝试=最大 attempt）
    prior_attempts = [int(l.get("attempt") or 0) for l in lines
                      if l.get("type") == "step" and l.get("step_id") == step_id]
    if prior_attempts and attempt <= max(prior_attempts):
        raise ValueError(f"step_id {step_id} 的 attempt 必须递增（已有 {max(prior_attempts)}）")
    # 后置条件逐键核验：来源=计划契约（2026-11-12 run2 教训）
    if step_result.get("status") == STATUS_OK:
        observed = step_result.get("observed_state") or {}
        missing = [key for key in plan_postconditions if key not in observed]
        if missing:
            raise ValueError(f"observed_state 缺少后置条件键 {missing}；拒绝落盘")
    postcondition_evidence = step_result.get("postcondition_evidence")
    if step_result.get("status") == STATUS_OK:
        pe = postcondition_evidence or []
        provided = {e.get("key") for e in pe}
        missing_pe = [k for k in plan_postconditions if k not in provided]
        if missing_pe:
            raise ValueError(f"postcondition_evidence 缺少后置条件 {missing_pe} 的证据绑定；"
                             "拒绝落盘（§4.1）")
        run_id = next((line.get("run_id") for line in lines
                       if line.get("type") == "run_start"), "unknown")
        for entry in pe:
            if entry.get("run_id") != run_id:
                raise ValueError(f"后置条件证据 {entry.get('key')} 的 run_id 与本会话不符；"
                                 "禁止混用另一会话证据")
    # 机器裁决先于落盘（S1.2 R1）：verdict 与观察一起持久化
    judged = dict(step_result)
    judged["postconditions"] = plan_postconditions
    verdict, verdict_reason = decide(judged)
    if step_result.get("status") == STATUS_OK and verdict != "CONTINUE":
        raise ValueError(f"status=ok 但机器裁决为 {verdict}（{verdict_reason}）；拒绝落盘")
    record = log.record_step(
        seq=step_result.get("seq", plan_step.get("seq", len(lines))),
        action=step_result["action"], params=step_result.get("params"),
        started_at=step_result.get("started_at"), ended_at=step_result.get("ended_at"),
        duration_ms=int(step_result.get("duration_ms") or 0), status=step_result["status"],
        error_code=step_result.get("error_code"),
        retries=int(step_result.get("retries") or 0),
        response_summary=step_result.get("response_summary"),
        evidence_ref=step_result.get("evidence_ref"),
        action_source=step_result.get("action_source"),
        execution_method=step_result.get("execution_method"),
        skip_reason=step_result.get("skip_reason"),
        required_for_goal=plan_step.get("required_for_goal", True),
        postcondition_evidence=postcondition_evidence,
        plan_hash=plan.get("plan_hash"), step_id=step_id, attempt=attempt,
        machine_verdict=verdict, machine_verdict_reason=verdict_reason)
    print(json.dumps({"verdict": verdict, "reason": verdict_reason,
                      "step_id": step_id, "attempt": attempt,
                      "recorded_seq": record["seq"]}, ensure_ascii=False))
    return 0 if verdict in ("CONTINUE", "WAITING_USER") else 1


def cmd_finish(args):
    session = Path(args.session_dir)
    log = ExecutionLog(session)
    lines = log.load_lines()
    if any(line.get("type") == "session_end" for line in lines):
        raise ValueError("会话已 finalize；拒绝重复 finish（S1.2 R1）")
    steps = [line for line in lines if line.get("type") == "step"]
    run_id = next((line.get("run_id") for line in lines
                   if line.get("type") == "run_start"), None)
    planned = {}
    steps_plan = session / "steps.json"
    if steps_plan.is_file():
        planned = {s["action"]: s for s in
                   json.loads(steps_plan.read_text(encoding="utf-8-sig")).get("steps", [])}
    # 机器裁决：goal_outcome 一律从计划+终局尝试推导（S1.2 R1）
    goal_outcome = compute_goal_outcome(steps, planned=planned)
    # 人工评估降级为注解：仅记录，永不覆盖机器裁决
    annotation = args.goal_outcome
    log.record_session_end(run_outcome=args.outcome, goal_outcome=goal_outcome,
                           goal_outcome_annotation=annotation,
                           note=args.note or None, finished_at=now(), run_id=run_id)
    summary = ["# 只读观测会话汇总", "",
               f"- 会话目录：{session}",
               f"- 结束时间：{now()}",
               f"- 运行结局（run_outcome）：{args.outcome}（{args.note or '无备注'}）",
               f"- 目标裁决（goal_outcome）：{goal_outcome}（机器计算，S1.2）",
               f"- 人工评估注解（goal_outcome_annotation）：{annotation or '无'}"
               "（仅注解，不参与裁决）",
               f"- 步骤数：{len(steps)}",
               *[f"- 步骤{line.get('seq')} {line.get('action')}：{line.get('status')}，"
                 f"必要={line.get('required_for_goal')}，"
                 f"裁决={line.get('machine_verdict')}，"
                 f"证据 {line.get('evidence_ref') or '无（失败/跳过）'}" for line in steps],
               "", "- 本会话为只读观测；不包含登录、下单、绕过验证或任何写操作。",
               "- 口径纠正（§1）：run_outcome=completed 只表示执行终止方式，"
               "不等于各必要动作实际执行成功；以机器 goal_outcome 为准。"]
    (session / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    print(json.dumps({"run_outcome": args.outcome, "goal_outcome": goal_outcome,
                      "goal_outcome_annotation": annotation, "steps": len(steps),
                      "summary": str(session / "summary.md")}, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--customer-ref", required=True)
    p_prepare.add_argument("--city", required=True)
    p_prepare.add_argument("--keyword", required=True)
    p_prepare.add_argument("--base", default=None, help="会话根目录（默认 reports/sessions）")
    p_prepare.set_defaults(func=cmd_prepare)

    p_record = sub.add_parser("record")
    p_record.add_argument("--session-dir", required=True)
    p_record.add_argument("--step-file", required=True)
    p_record.set_defaults(func=cmd_record)

    p_finish = sub.add_parser("finish")
    p_finish.add_argument("--session-dir", required=True)
    p_finish.add_argument("--outcome", required=True,
                          choices=["completed", "aborted", "waiting_user"])
    p_finish.add_argument("--goal-outcome", default=None,
                          choices=["satisfied", "partial", "blocked", "failed"],
                          help="目标裁决；缺省时由 required_for_goal 自动计算（§4.1）")
    p_finish.add_argument("--note", default="")
    p_finish.set_defaults(func=cmd_finish)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
