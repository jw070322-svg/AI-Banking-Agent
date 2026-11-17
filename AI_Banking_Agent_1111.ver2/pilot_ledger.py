"""工作包C真实试点台账 v2（S1.1，修复评审 R2——AGENT_REVIEW_AND_CONTINUATION_PLAN_20261116.md）。

修复清单（每项对应 failing-before/passing-after 测试，见 test_pilot_ledger.py）：
- 默认路径：_ledger_path(None) 返回 DEFAULT_LEDGER（原 Path(None) 崩溃，评审复现）。
- 原子持久化：临时文件 + os.replace（原全文件重写无保护）。
- start 来源绑定：session_dir 必须已存在且含 run.jsonl/run_start；必须提供真实来源文件路径，
  record_id 须在该文件唯一可解析；记录含 synthetic/test_only 标记即拒绝（调用方标签不可信）；
  city 从来源记录推导，调用方所报城市不一致即拒绝（防串客）。
- finish 结局推导：run_outcome/goal_outcome/user_takeover 一律从会话 run.jsonl（session_end
  与步骤）推导；CLI 断言仅作交叉校验，不一致即拒绝（原为调用方断言直接采信）。
- 证据纪律：finish 至少 1 条证据引用；引用必须携带完整 64 位十六进制 SHA256 且文件存在、
  哈希匹配（原接受空证据与前缀比较）。
- 墙分类：waiting_user 仅在步骤证据命中强制墙特征（executor.base.FORCE_WALL_KEYWORDS）时
  计为 verification wall（原全部 waiting_user 都算墙）。
- stats：started/open/closed/invalid 四计数；率值附显式分子/分母；closed=0 → not_evaluated
  （原 0 运行也会产出率值）；非 local_real_file 行单独计数并排除于率值。
- verify：仅接受全哈希引用；前缀引用记为发现（原接受前缀比较）。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from executor.base import FORCE_WALL_KEYWORDS  # noqa: E402
from executor.base import sha256_of  # noqa: E402

DEFAULT_LEDGER = Path(__file__).parent / "reports" / "pilot_C" / "ledger.jsonl"
SCENARIOS = ("normal", "missing_params", "negation", "multi_category",
             "no_result", "verification_wall", "price_missing")
RUN_OUTCOMES = ("completed", "aborted", "waiting_user")
GOAL_OUTCOMES = (GOAL_SATISFIED := "satisfied", GOAL_PARTIAL := "partial",
                 GOAL_BLOCKED := "blocked", GOAL_FAILED := "failed")
EXPECTED_SCENARIOS = set(SCENARIOS)
REAL_SOURCE_KIND = "local_real_file"
FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _ledger_path(ledger):
    """S1.1 修复：None → DEFAULT_LEDGER（原 Path(None) 崩溃）。"""
    return Path(ledger) if ledger else DEFAULT_LEDGER


def _load(ledger=None):
    path = _ledger_path(ledger)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _save(rows, ledger=None):
    """S1.1 修复：原子持久化（临时文件 + os.replace）。"""
    path = _ledger_path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _check_evidence_ref(base_dir, ref):
    """全哈希 + 文件存在 + 哈希匹配；返回发现或 None（S1.1：拒绝前缀与空证据）。"""
    rel = ref.split("#")[0]
    claimed = ref.split("#sha256:", 1)[1] if "#sha256:" in ref else None
    if not claimed or not FULL_SHA256.match(claimed):
        return {"status": "hash_format_invalid",
                "detail": f"{rel}：缺少完整64位十六进制SHA256（前缀比较已废除）"}
    path = Path(base_dir) / rel
    if not path.is_file():
        return {"status": "evidence_missing", "detail": rel}
    if not sha256_of(path).startswith(claimed):
        return {"status": "hash_mismatch", "detail": rel}
    return None


def _session_facts(session_dir):
    """读取会话 run.jsonl：要求已 finalize（session_end）；推导结局/接管/墙标记。"""
    path = Path(session_dir) / "run.jsonl"
    if not path.is_file():
        raise ValueError(f"会话缺少 run.jsonl：{session_dir}")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if not any(line.get("type") == "run_start" for line in lines):
        raise ValueError(f"会话缺少 run_start 记录：{session_dir}")
    session_end = next((line for line in lines if line.get("type") == "session_end"), None)
    if session_end is None:
        raise ValueError(f"会话未 finalize（缺少 session_end）：{session_dir}；"
                         "先执行 run_session finish 再闭合试点")
    steps = [line for line in lines if line.get("type") == "step"]
    wall_blocked = False
    if session_end.get("run_outcome") == "waiting_user":
        for step in steps:
            haystack = " ".join(filter(None, [step.get("error_code"),
                                              step.get("response_summary")]))
            if any(k in haystack for k in FORCE_WALL_KEYWORDS):
                wall_blocked = True
                break
    user_takeover = (session_end.get("run_outcome") == "waiting_user"
                     or any(step.get("action_source") == "user_takeover" for step in steps))
    return {"run_outcome": session_end.get("run_outcome"),
            "goal_outcome": session_end.get("goal_outcome"),
            "user_takeover": user_takeover,
            "wall_blocked": wall_blocked,
            "run_id": next((line.get("run_id") for line in lines
                            if line.get("type") == "run_start"), None)}


def _verify_source_binding(record_id, source_path, claimed_city):
    """S1.1 来源绑定：记录须在真实来源文件中唯一可解析；synthetic/test_only 拒绝；
    city 从来源记录推导，调用方所报不一致即拒绝（防串客）。"""
    if not source_path:
        raise ValueError("start 必须提供真实来源文件路径（--source-path）；不自动选客")
    path = Path(source_path)
    if not path.is_file():
        raise ValueError(f"真实来源文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"真实来源JSON非法：{exc}") from None
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise ValueError("真实来源结构非法：缺少 records 列表")
    matches = [r for r in records if isinstance(r, dict) and r.get("record_id") == record_id]
    if not matches:
        raise ValueError(f"真实来源中不存在记录：{record_id}；不自动换客")
    if len(matches) > 1:
        raise ValueError(f"真实来源内存在 {len(matches)} 条重复 record_id：{record_id}")
    record = matches[0]
    if record.get("synthetic") or record.get("test_only"):
        raise ValueError(f"记录 {record_id} 带有 synthetic/test_only 标记——合成不计真实试点；"
                         "调用方 local_real_file 标签不能改变记录本身性质")
    derived_city = record.get("city")
    if claimed_city != derived_city:
        raise ValueError(f"跨客户防护：来源记录 city={derived_city!r}，调用方所报 "
                         f"{claimed_city!r} 不一致；拒绝")
    return {"city": derived_city, "source_fingerprint":
            hashlib_sha16(json.dumps(record, sort_keys=True, ensure_ascii=False))}


def hashlib_sha16(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def start(record_id, scenario, city, source_kind, session_dir,
          source_path=None, variant_of=None, notes=None, ledger=None):
    """登记一次试点运行开始。S1.1：来源绑定 + 会话必须先经 prepare 创建。"""
    if source_kind != REAL_SOURCE_KIND:
        raise ValueError(f"试点台账只接受 source_kind={REAL_SOURCE_KIND}；"
                         f"收到 {source_kind!r}（合成fixtures不计入真实试点）")
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario 必须为 {SCENARIOS} 之一；额外标签写 notes")
    if not record_id or not city:
        raise ValueError("record_id 与 city 必填；不自动选客")
    session = Path(session_dir)
    if not session.is_dir():
        raise ValueError(f"session_dir 不存在：{session}（先 run_session prepare 创建，"
                         "再登记试点）")
    if not (session / "run.jsonl").is_file():
        raise ValueError(f"session_dir 缺少 run.jsonl：{session}")
    binding = _verify_source_binding(record_id, source_path, city)
    rows = _load(ledger)
    duplicate = [r for r in rows if r.get("record_id") == record_id
                 and r.get("scenario") == scenario
                 and r.get("city") == binding["city"]
                 and r.get("run_outcome") is None]
    if duplicate:
        raise ValueError(f"同记录同场景同城市已有未闭合试点：{duplicate[0]['pilot_id']}")
    pilot_id = f"P-{len(rows) + 1:03d}"
    row = {"type": "pilot_run", "pilot_id": pilot_id,
           "record_id": record_id, "scenario": scenario, "city": binding["city"],
           "source_kind": source_kind, "source_path": str(source_path),
           "source_fingerprint": binding["source_fingerprint"],
           "variant_of": variant_of,
           "session_dir": str(session), "started_at": _now(),
           "run_outcome": None, "goal_outcome": None, "user_takeover": None,
           "wall_blocked": None, "evidence_refs": [], "notes": notes}
    rows.append(row)
    _save(rows, ledger)
    return row


def finish(pilot_id, run_outcome=None, goal_outcome=None, user_takeover=None,
           evidence_refs=None, notes=None, ledger=None):
    """闭合试点：结局/接管一律从会话推导（S1.1）；CLI 断言仅作交叉校验，
    与推导不一致即拒绝。"""
    rows = _load(ledger)
    row = next((r for r in rows if r.get("pilot_id") == pilot_id
                and r.get("type") == "pilot_run"), None)
    if row is None:
        raise FileNotFoundError(f"台账中不存在试点：{pilot_id}")
    if row.get("run_outcome") is not None:
        raise ValueError(f"试点 {pilot_id} 已闭合，不得重复 finish")
    facts = _session_facts(row["session_dir"])
    if run_outcome is not None and run_outcome != facts["run_outcome"]:
        raise ValueError(f"run_outcome 断言 {run_outcome!r} 与会话推导 "
                         f"{facts['run_outcome']!r} 不一致；拒绝")
    if goal_outcome is not None and goal_outcome != facts["goal_outcome"]:
        raise ValueError(f"goal_outcome 断言 {goal_outcome!r} 与会话推导 "
                         f"{facts['goal_outcome']!r} 不一致；拒绝")
    if user_takeover is not None and bool(user_takeover) != facts["user_takeover"]:
        raise ValueError(f"user_takeover 断言 {user_takeover!r} 与会话推导 "
                         f"{facts['user_takeover']!r} 不一致；拒绝")
    refs = list(evidence_refs or [])
    if not refs:
        raise ValueError("finish 至少需要 1 条证据引用；空证据不得闭合（S1.1）")
    findings = [f for f in (_check_evidence_ref(row["session_dir"], ref)
                            for ref in refs) if f]
    if findings:
        raise ValueError(f"证据复验未通过：{findings}；拒绝闭合")
    row["run_outcome"] = facts["run_outcome"]
    row["goal_outcome"] = facts["goal_outcome"]
    row["user_takeover"] = facts["user_takeover"]
    row["wall_blocked"] = facts["wall_blocked"]
    row["evidence_refs"] = refs
    row["finished_at"] = _now()
    if notes:
        row["notes"] = ((row.get("notes") or "") + " | " + notes).strip(" |")
    _save(rows, ledger)
    return row


def _row_invalid(row):
    if row.get("type") != "pilot_run":
        return "非试点行"
    if row.get("scenario") not in SCENARIOS:
        return "scenario 非法"
    if row.get("source_kind") != REAL_SOURCE_KIND:
        return "来源非 local_real_file"
    if not row.get("record_id") or not row.get("session_dir"):
        return "缺少 record_id/session_dir"
    return None


def stats(ledger=None):
    """四率 + 覆盖矩阵（S1.1：四计数、显式分子分母、墙分类收严、零运行 not_evaluated）。"""
    rows = [r for r in _load(ledger) if r.get("type") == "pilot_run"]
    invalid = [{"pilot_id": r.get("pilot_id"), "reason": reason}
               for r, reason in ((r, _row_invalid(r)) for r in rows) if reason]
    valid = [r for r in rows if not _row_invalid(r)]
    started = len(rows)
    closed = [r for r in valid if r.get("run_outcome") is not None]
    open_rows = [r for r in valid if r.get("run_outcome") is None]
    total = len(closed)
    if total == 0:
        return {"status": "not_evaluated",
                "reason": "无已闭合试点运行；不得宣称试点通过",
                "started": started, "open": len(open_rows),
                "closed": 0, "invalid": invalid,
                "non_real_source_rows": sum(1 for r in rows
                                             if r.get("source_kind") != REAL_SOURCE_KIND)}
    satisfied = [r for r in closed if r["goal_outcome"] == "satisfied"]
    takeover = [r for r in closed if r.get("user_takeover")]
    wall_blocked = [r for r in closed if r.get("wall_blocked")]
    auto = [r for r in satisfied if not r.get("user_takeover")]
    denom_controlled = total - len(wall_blocked)

    def rate(numerator, denominator):
        return round(numerator / denominator, 4) if denominator else None

    matrix = {}
    for row in closed:
        entry = matrix.setdefault(f"{row['scenario']}@{row['city']}",
                                  {"total": 0, "satisfied": 0})
        entry["total"] += 1
        entry["satisfied"] += row["goal_outcome"] == "satisfied"
    return {
        "status": "evaluated",
        "started": started, "open": len(open_rows), "closed": total,
        "invalid": invalid,
        "auto_completion_rate": rate(len(auto), total),
        "user_takeover_rate": rate(len(takeover), total),
        "controlled_environment_completion_rate": rate(len(satisfied), denom_controlled),
        "overall_success_rate": rate(len(satisfied), total),
        "rate_numerators_denominators": {
            "auto_completion": f"{len(auto)}/{total}",
            "user_takeover": f"{len(takeover)}/{total}",
            "controlled_environment": f"{len(satisfied)}/{denom_controlled}",
            "overall_success": f"{len(satisfied)}/{total}"},
        "counts": {"satisfied": len(satisfied), "auto_satisfied": len(auto),
                    "takeover": len(takeover),
                    "wall_blocked": len(wall_blocked),
                    "other_blocked_or_failed": total - len(satisfied)},
        "coverage_matrix": matrix,
        "missing_scenarios": sorted(EXPECTED_SCENARIOS -
                                    {r["scenario"] for r in closed}),
        "non_real_source_rows": sum(1 for r in rows
                                     if r.get("source_kind") != REAL_SOURCE_KIND),
        "rate_definitions": {
            "auto_completion": "goal=satisfied 且无用户接管 / closed",
            "user_takeover": "user_takeover=True / closed",
            "controlled_environment": "goal=satisfied / (closed − 确认墙阻断)",
            "overall_success": "goal=satisfied / closed"},
    }


def verify(ledger=None, base_dir=None):
    """逐行证据复验（S1.1：全哈希强制，前缀引用即发现；路径相对各自 session_dir）。"""
    findings = []
    rows = _load(ledger)
    for row in rows:
        if row.get("type") != "pilot_run":
            continue
        for ref in row.get("evidence_refs") or []:
            finding = _check_evidence_ref(row.get("session_dir") or base_dir or ".", ref)
            if finding:
                findings.append({"pilot_id": row.get("pilot_id"), **finding})
    return {"rows": len(rows), "findings": findings, "pass": not findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("--record-id", required=True)
    p_start.add_argument("--scenario", required=True, choices=SCENARIOS)
    p_start.add_argument("--city", required=True)
    p_start.add_argument("--source-kind", required=True)
    p_start.add_argument("--source-path", required=True)
    p_start.add_argument("--session-dir", required=True)
    p_start.add_argument("--variant-of", default=None)
    p_start.add_argument("--notes", default=None)
    p_start.add_argument("--ledger", default=None)

    p_finish = sub.add_parser("finish")
    p_finish.add_argument("--pilot-id", required=True)
    p_finish.add_argument("--run-outcome", choices=RUN_OUTCOMES, default=None,
                          help="交叉校验用；缺省从会话推导（S1.1）")
    p_finish.add_argument("--goal-outcome", choices=GOAL_OUTCOMES, default=None,
                          help="交叉校验用；缺省从会话推导（S1.1）")
    p_finish.add_argument("--user-takeover", choices=["true", "false"], default=None,
                          help="交叉校验用；缺省从会话推导（S1.1）")
    p_finish.add_argument("--evidence-refs", required=True)
    p_finish.add_argument("--notes", default=None)
    p_finish.add_argument("--ledger", default=None)

    for name in ("stats", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--ledger", default=None)

    args = parser.parse_args()
    if args.command == "start":
        row = start(args.record_id, args.scenario, args.city, args.source_kind,
                    args.session_dir, source_path=args.source_path,
                    variant_of=args.variant_of, notes=args.notes, ledger=args.ledger)
        print(json.dumps({"pilot_id": row["pilot_id"], "status": "started",
                           "city": row["city"]}, ensure_ascii=False))
    elif args.command == "finish":
        takeover = None if args.user_takeover is None else args.user_takeover == "true"
        refs = [r for r in args.evidence_refs.split(",") if r.strip()]
        row = finish(args.pilot_id, args.run_outcome, args.goal_outcome, takeover,
                     evidence_refs=refs, notes=args.notes, ledger=args.ledger)
        print(json.dumps({"pilot_id": row["pilot_id"], "status": "closed",
                           "run_outcome": row["run_outcome"],
                           "goal_outcome": row["goal_outcome"],
                           "wall_blocked": row["wall_blocked"]}, ensure_ascii=False))
    elif args.command == "stats":
        print(json.dumps(stats(args.ledger), ensure_ascii=False, indent=2))
    elif args.command == "verify":
        print(json.dumps(verify(args.ledger), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
