"""Local deterministic core. Does not claim to execute Dianping or train Qwen."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from lexicon import BUILTIN_RULES, LexiconError, extract_keywords, load_lexicon
from schema_check import SchemaValidationError, load_schema, validate

def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()

def cents(value):
    if isinstance(value, bool):
        raise ValueError("金额不能是布尔值")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("金额必须是数值") from None
    if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
        raise ValueError("金额必须为非负有限数，最多两位小数")
    return int(amount * 100)

def build_plan(customer):
    """Customer is an explicit canonical record, never selected from filesystem implicitly."""
    errors = []
    city = customer.get("city", "")
    if not isinstance(city, str) or not re.fullmatch(r"[\u4e00-\u9fffA-Za-z ·-]{1,40}", city.strip()):
        errors.append("缺少或无效的客户城市")
    event = customer.get("special_event", "")
    if not isinstance(event, str):
        event = ""
    try:
        lexicon = load_lexicon()
        keywords, negated_keywords, review_flags = extract_keywords(event, lexicon)
        keyword_source = "lexicon_" + lexicon["lexicon_version"] + "_rule_baseline_not_qwen"
    except LexiconError:
        keywords = list(dict.fromkeys(k for term, values in BUILTIN_RULES.items() if term in event for k in values))
        negated_keywords, review_flags = [], []
        keyword_source = "builtin_rules_fallback_not_qwen"
    if not keywords:
        errors.append("事件未覆盖：需要客户确认服务品类或模型候选人工确认")
    b = customer.get("budget", {})
    if not isinstance(b, dict):
        b = {}
    normalized = None
    try:
        if b.get("currency") != "CNY":
            raise ValueError("需明确人民币预算，不自动换汇")
        lower, upper = cents(b.get("min", "0")), cents(b.get("max"))
        if lower > upper:
            raise ValueError("预算下限不能大于上限")
        if b.get("basis") not in ("per_person", "total"):
            raise ValueError("预算口径缺失：人均或总额")
        normalized = {"min_cents": lower, "max_cents": upper, "basis": b["basis"], "currency": "CNY"}
    except ValueError as exc:
        errors.append(str(exc))
    people = customer.get("party_size")
    if people is not None and (type(people) is not int or people <= 0):
        errors.append("人数必须为正整数")
    location = customer.get("location_mode", "city_only")
    if location not in ("city_only", "device"):
        errors.append("定位模式无效")
    if location == "device":
        errors.append("设备定位需确认目标用户设备及点评定位授权；不得使用操作员设备冒充客户位置")
    steps = [
        {"action": "open_site", "params": {"url": "https://www.dianping.com/"}, "verify": "域名和页面可访问"},
        {"action": "select_city", "params": {"city_name": city}, "verify": "页面选中城市与客户城市一致"},
        {"action": "resolve_location", "params": {"mode": location}, "verify": "city_only不宣称GPS定位；设备定位需授权、精度与城市核验"},
        {"action": "search", "params": {"keywords": keywords}, "verify": "逐个品类提交，核对结果页关键词及城市"},
        {"action": "filter_price", "params": {"budget": normalized}, "verify": "匹配价格口径，页面档位粗筛后本地精筛；不跨品类共用整笔预算"},
    ]
    plan = {"schema_version": 1, "created_at": now(), "status": "needs_input" if errors else "planned",
            "mode": "plan_only", "city": city, "keywords": keywords,
            "keyword_source": keyword_source, "budget": normalized, "party_size": people,
            "issues": errors, "steps": steps, "live_executed": False,
            "negated_keywords": negated_keywords, "review_flags": review_flags,
            "budget_fingerprint": (hashlib.sha256(json.dumps(
                {"budget": normalized, "party_size": people},
                sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
                if normalized else None),
            "customer_ref_snapshot": None}  # 工作包C 接线后由客户来源适配器填充
    validate(plan, load_schema("plan.schema.json"))  # 契约自检：内部不一致时快速失败
    return plan

def filter_candidates(items, budget, party_size=None):
    """Filter one service category. Estimates are candidates, never final payable guarantees.

    Phase 3（G5 修复）：所有输出桶携带可得的价格证据（原口径分值、口径、类型、
    来源、采集时间、换算结果），保证筛选结论可审计。
    """
    accepted, rejected, unknown = [], [], []
    for item in items:
        record = {"id": item.get("id")}
        if isinstance(item.get("name"), str):
            record["name"] = item["name"]
        try:
            validate(item, load_schema("merchant_item.schema.json"), path="merchant_item")
        except SchemaValidationError as exc:
            unknown.append({**record, "reason": "结构校验失败：" + str(exc)})
            continue
        price_evidence = {}
        try:
            if item.get("currency") != "CNY":
                raise ValueError("币种缺失或不匹配")
            price_evidence["price_min_cents"] = cents(item["price_min"])
            price_evidence["price_max_cents"] = cents(item["price_max"])
            lo = price_evidence["price_min_cents"]
            hi = price_evidence["price_max_cents"]
            if lo > hi:
                raise ValueError("价格区间无效")
            basis = item.get("basis")
            if basis not in ("per_person", "total"):
                raise ValueError("价格口径未知")
            price_evidence["basis"] = basis
            divisor = 1
            if basis != budget["basis"]:
                if type(party_size) is not int or party_size <= 0:
                    raise ValueError("换算总额与人均需要人数")
                if basis == "per_person":
                    lo, hi = lo * party_size, hi * party_size
                else:
                    divisor = party_size
            if item.get("price_kind") not in ("listed", "average") or not item.get("source_url") or not item.get("observed_at"):
                raise ValueError("缺少价格类型、来源或采集时间")
            if item.get("conditional", False):
                raise ValueError("优惠或套餐资格未确认")
            record.update(price_evidence)
            record.update({
                "price_kind": item["price_kind"],
                "estimated": item["price_kind"] == "average",
                "currency": "CNY",
                "source_url": item["source_url"],
                "observed_at": item["observed_at"],
                "converted": {"basis": budget["basis"], "min_cents": lo, "max_cents": hi,
                              "party_size": party_size if divisor != 1 else None},
            })
            if lo >= budget["min_cents"] * divisor and hi <= budget["max_cents"] * divisor:
                accepted.append(record)
            elif hi < budget["min_cents"] * divisor or lo > budget["max_cents"] * divisor:
                rejected.append({**record, "reason": "超出预算区间"})
            else:
                unknown.append({**record, "reason": "价格区间部分重叠，需确认实际价格"})
        except (KeyError, ValueError) as exc:
            unknown.append({**record, **price_evidence, "reason": str(exc)})
    return {"candidates": accepted, "excluded": rejected, "needs_confirmation": unknown,
            "notice": "候选价格匹配不保证实际结算；不同品类需分配预算或计算组合总价"}


def allocate_budget(items_by_category, budget, party_size=None, known_surcharges=None):
    """多品类预算组合验证（DESIGN §5）。纯本地逻辑。

    各品类先过单品类筛选（filter_candidates），组合层验证所选候选换算后
    最坏区间 + 已知附加费是否落在预算内。数据缺失按 issues 如实返回：
    不推定人数、不虚构价格、不把估算当结算价。
    """
    if not isinstance(budget, dict) or "max_cents" not in budget:
        raise ValueError("预算缺失或无效：无法做组合验证")
    combination, per_category, issues, surcharges = {}, {}, [], []
    total_min = total_max = 0
    if not items_by_category:
        issues.append("未提供任何品类候选")
    for category, items in (items_by_category or {}).items():
        result = filter_candidates(list(items or []), budget, party_size)
        per_category[category] = {"candidates": len(result["candidates"]),
                                  "excluded": len(result["excluded"]),
                                  "needs_confirmation": len(result["needs_confirmation"])}
        if not result["candidates"]:
            issues.append(f"品类「{category}」无可用候选：待确认 {len(result['needs_confirmation'])} 条 / 超界 {len(result['excluded'])} 条")
            continue
        chosen = min(result["candidates"],
                     key=lambda r: (r["price_max_cents"], 0 if r["price_kind"] == "listed" else 1))
        combination[category] = chosen
        total_min += chosen["converted"]["min_cents"]
        total_max += chosen["converted"]["max_cents"]
    for surcharge in (known_surcharges or []):
        if (not isinstance(surcharge, dict) or not isinstance(surcharge.get("name"), str)
                or type(surcharge.get("amount_cents")) is not int or surcharge["amount_cents"] < 0):
            raise ValueError("附加费格式无效：需 {name: str, amount_cents: 非负整数}")
        surcharges.append({"name": surcharge["name"], "amount_cents": surcharge["amount_cents"]})
        total_min += surcharge["amount_cents"]
        total_max += surcharge["amount_cents"]
    max_cents = budget["max_cents"]
    if issues:
        verdict = "infeasible_with_current_evidence"
    elif total_max <= max_cents:
        verdict = "within_budget"
    elif total_min <= max_cents:
        verdict = "partial_overlap_needs_confirmation"
    else:
        verdict = "over_budget"
    return {"schema_version": 1, "verdict": verdict, "combination": combination,
            "surcharges": surcharges, "best_case_cents": total_min,
            "worst_case_cents": total_max, "budget_max_cents": max_cents,
            "budget_basis": budget["basis"], "party_size": party_size,
            "issues": issues, "per_category": per_category,
            "notice": "组合验证基于页面参考价区间与已知附加费，不保证实际结算；优惠/套餐资格、日期与变动费用另核"}

def _load_execution_log(path):
    """读取 run.jsonl 并逐行按契约校验（坏行拒绝，不静默跳过）。"""
    records = []
    schema = load_schema("execution_log.schema.json")
    for index, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        try:
            validate(record, schema)
        except SchemaValidationError as exc:
            raise ValueError(f"执行日志第{index}行不符合契约：{exc}") from None
        records.append(record)
    if not records:
        raise ValueError("执行日志为空")
    return records


def write_handoff(plan, output, execution_log=None):
    """生成交接目录。提供 execution_log（run.jsonl 路径）时按 DESIGN §7
    回填真实执行字段（每步动作/状态/耗时/重试/错误码/证据）；未提供时
    如实写“执行记录：无（plan_only）”，绝不填模拟成功。"""
    validate(plan, load_schema("plan.schema.json"))  # 交接只接受通过契约自检的计划
    doc = dict(plan)
    output = Path(output) / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    lines = ["# 自动化运行交接", "", "- 时间：" + plan["created_at"], "- 状态：" + plan["status"],
             "- 模式：plan_only；仅生成计划，未执行真实页面。",
             "- 关键词来源：" + plan.get("keyword_source", "未知") + "（规则基线，非千问推理）。",
             "", "## 步骤与接口"]
    for step in plan["steps"]:
        lines.extend(["", "- 本地契约：" + step["action"], "  - 参数：" + json.dumps(step["params"], ensure_ascii=False), "  - 验证：" + step["verify"]])
    if execution_log is not None:
        records = _load_execution_log(execution_log)
        steps = [r for r in records if r.get("type") == "step"]
        session_end = next((r for r in records if r.get("type") == "session_end"), None)
        run_outcome = (session_end or {}).get("run_outcome", "not_recorded_in_log")
        goal_outcome = (session_end or {}).get("goal_outcome", "unknown")
        doc["execution"] = {"log_path": str(execution_log), "backfilled_at": now(),
                            "outcome": run_outcome, "run_outcome": run_outcome,
                            "goal_outcome": goal_outcome, "steps": steps,
                            "attachments": []}
        lines.extend(["", "## 执行记录（回填自 run.jsonl）",
                      f"- 运行结局：{run_outcome}；目标裁决：{goal_outcome}"
                      "（§4.1 双结局，completed 不等于目标满足）"])
        for r in steps:
            line = (f"- 步骤{r.get('seq')} {r.get('action')}：{r.get('status')}，"
                    f"耗时 {r.get('duration_ms')}ms，重试 {r.get('retries')}")
            if r.get("error_code"):
                line += f"，错误 {r['error_code']}"
            if r.get("evidence_ref"):
                line += f"，证据 {r['evidence_ref']}"
            lines.append(line)
        lines.append(f"- 来源：{execution_log}（{len(steps)} 个步骤记录；结论以各步 response_summary 为准）")
    else:
        lines.extend(["", "- 执行记录：无（plan_only）"])
    validate(doc, load_schema("plan.schema.json"))  # 合并执行块后再次契约自检
    flags = plan.get("review_flags") or []
    if flags:
        lines.extend(["", "## 复核标记（不改状态，需人工或模型复核）", *["- " + f for f in flags]])
    lines.extend(["", "## 阻塞与待办", *["- " + x for x in plan["issues"]],
                  "- 接入真实客户字段与浏览器执行器，记录每步请求、结果、证据和耗时。",
                  "- 新权重训练和对照评测未进行；不得报告模型提升或端到端完成。"])
    (output / "handoff.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "handoff.md").write_text("\n".join(lines), encoding="utf-8")
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("customer", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "reports")
    parser.add_argument("--execution-log", type=Path, default=None,
                        help="run.jsonl 路径：提供时按 DESIGN §7 回填真实执行字段")
    args = parser.parse_args()
    plan = build_plan(json.loads(args.customer.read_text(encoding="utf-8-sig")))
    print(write_handoff(plan, args.output, execution_log=args.execution_log))
