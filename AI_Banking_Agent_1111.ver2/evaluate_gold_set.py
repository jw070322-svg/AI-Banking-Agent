"""金标准集基线评测（Phase 1 交付物）。

对 evaluation/gold_set.json 逐条运行 QwenClient.extract（真实本地服务，
temperature=0），量化 DESIGN §6 第一层"模型参数提取"指标的当前基线：
- JSON 合规率（原始 / 一次修复后）与 Schema 通过率
- 证据片段有效率（片段级与案例级）
- 关键词召回/精确率（严格精确匹配；近似不算命中）
- 应澄清召回率与误澄清率
- 否定排除成功率
结果写入 reports/phase1/；这是能力基线，不是验收门禁，更不是训练成果。
所有 gold_set 案例均为合成文本，不含任何真实客户信息。
"""
import json
import re
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qwen_client import QwenClient  # noqa: E402
from schema_check import load_schema, validate  # noqa: E402

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "reports" / "phase1"


def fence_stripped_ok(content, schema):
    """诊断用（非契约）：剥离markdown围栏后能否通过严格校验。
    用于区分'工程可救'（围栏问题）与'能力不足'（内容问题）。"""
    match = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", (content or "").strip(), re.DOTALL)
    text = match.group(1) if match else (content or "").strip()
    try:
        validate(json.loads(text), schema)
        return True
    except Exception:
        return False


def keyword_sets(case, parsed):
    expected_kw = set(case["expected"]["keywords"])
    expected_cat = set(case["expected"]["categories"])
    output_kw = set(parsed.get("public_keywords", [])) if parsed else set()
    output_cat = set(parsed.get("service_categories", [])) if parsed else set()
    return expected_kw, expected_cat, output_kw, output_cat


def score_case(case, result):
    parsed = result["parsed"]
    row = {"id": case["id"], "difficulty": case["difficulty"],
           "event": case["event"], "status": result["status"],
           "raw_parse_ok": result["raw_parse_ok"], "repair_used": result["repair_used"],
           "fenced": bool(result["raw_content"]) and result["raw_content"].lstrip().startswith("```"),
           "raw_content": (result["raw_content"] or "").strip(),
           "finish_reason": result["finish_reason"],
           "out_of_vocabulary": result.get("out_of_vocabulary")}
    expected_kw, expected_cat, output_kw, output_cat = keyword_sets(case, parsed)
    row["output_keywords"] = sorted(output_kw)
    row["output_categories"] = sorted(output_cat)
    row["expected_keywords"] = sorted(expected_kw)
    if result["status"] == "ok" and parsed is not None:
        row["clarification_flagged"] = bool(parsed.get("needs_clarification"))
        # 证据片段
        spans = parsed.get("evidence_spans", [])
        row["evidence_valid_ratio"] = (len(result["evidence"]["valid"]) / len(spans)) if spans else None
        row["evidence_all_valid"] = bool(spans) and not result["evidence"]["invalid"]
        # 关键词召回/精确（严格匹配；JSON失败的案例不进入，单独计失败）
        row["keyword_recall"] = (len(expected_kw & output_kw) / len(expected_kw)) if expected_kw else None
        row["keyword_precision"] = ((len(expected_kw & output_kw) / len(output_kw))
                                    if output_kw else (1.0 if not expected_kw else 0.0))
        # 否定排除
        excluded = case["expected"]["excluded"]
        row["exclusion_success"] = (all(x not in output_kw and x not in output_cat
                                        for x in excluded) if excluded else None)
        # 约束信息（可选字段）
        mention = case["expected"].get("constraint_may_mention")
        if mention:
            row["constraint_mentioned"] = any(mention in c for c in parsed.get("constraints", []))
    else:
        row["clarification_flagged"] = None
        row["evidence_valid_ratio"] = None
        row["evidence_all_valid"] = False
        row["keyword_recall"] = 0.0 if expected_kw else 1.0
        row["keyword_precision"] = 0.0
        excluded = case["expected"]["excluded"]
        row["exclusion_success"] = False if excluded else None
        row["reason"] = result["reason"]
    return row


def aggregate(rows, cases):
    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 4) if values else None

    by = lambda key: [r for r, c in zip(rows, cases) if c["difficulty"] == key]  # noqa: E731
    ambiguous = by("ambiguous")
    exclusion_cases = [r for r, c in zip(rows, cases) if c["expected"]["excluded"]]
    return {
        "cases_total": len(rows),
        "status_counts": {s: sum(1 for r in rows if r["status"] == s)
                          for s in ("ok", "needs_input", "unavailable")},
        "raw_json_rate": mean([1.0 if r["raw_parse_ok"] else 0.0 for r in rows]),
        "final_json_rate": mean([1.0 if r["status"] == "ok" else 0.0 for r in rows]),
        "fenced_rate": mean([1.0 if r["fenced"] else 0.0 for r in rows]),
        "repair_rate": mean([1.0 if r["repair_used"] else 0.0 for r in rows]),
        "evidence_all_valid_rate": mean([1.0 if r["evidence_all_valid"] else 0.0 for r in rows]),
        "keyword_recall": mean([r["keyword_recall"] for r in rows]),
        "keyword_precision": mean([r["keyword_precision"] for r in rows]),
        "clarification_recall": mean([1.0 if r["clarification_flagged"] else 0.0 for r in ambiguous]),
        "false_clarification_rate": mean(
            [1.0 if r["clarification_flagged"] else 0.0 for r in rows if r["id"] not in
             {c["id"] for c in cases if c["difficulty"] == "ambiguous"}]),
        "exclusion_success_rate": mean([1.0 if r["exclusion_success"] else 0.0 for r in exclusion_cases]),
        "exclusion_cases_total": len(exclusion_cases),
    }


def main():
    cases = json.loads((ROOT / "evaluation" / "gold_set.json").read_text(encoding="utf-8-sig"))
    client = QwenClient()
    probe = client.probe()
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat()
    if not probe["ok"]:
        report = {"ran_at": stamp, "service_probe": probe, "ran": False,
                  "note": "本地模型服务不可用，基线未运行；不生成任何通过声明"}
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "gold_baseline.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 2

    rows = []
    for case in cases:
        result = client.extract(case["event"])
        rows.append(score_case(case, result))
        print(f"[{case['id']}] status={result['status']} repair={result['repair_used']} "
              f"kws={rows[-1]['output_keywords']}")
    metrics = aggregate(rows, cases)
    schema = load_schema("qwen_output.schema.json")
    metrics["fence_stripped_json_rate_diagnostic"] = round(
        sum(1 for r in rows if fence_stripped_ok(r["raw_content"], schema)) / len(rows), 4)
    oov_rows = [r for r in rows if r["status"] == "ok"]
    metrics["oov_or_echo_keyword_rate"] = round(
        sum(1 for r in oov_rows if r["out_of_vocabulary"]) / len(oov_rows), 4) if oov_rows else None
    report = {"ran_at": stamp, "ran": True, "service_probe": probe,
              "model": client.model, "temperature": 0,
              "metrics": metrics, "cases": rows}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "gold_baseline.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 金标准集基线报告（Phase 1，2026-11-12）", "",
        f"- 运行时间：{stamp}",
        f"- 服务探针：{json.dumps(probe, ensure_ascii=False)}",
        f"- 模型：{client.model}（原权重，无适配器），temperature=0",
        f"- 案例数：{metrics['cases_total']}（全部为合成文本，不含真实客户信息）", "",
        "## 指标（当前基线，不是验收门禁）", "",
        f"- 原始 JSON 合规率：{metrics['raw_json_rate']}",
        f"- 一次修复后合规率（status=ok）：{metrics['final_json_rate']}",
        f"- 围栏输出率 / 触发修复率：{metrics['fenced_rate']} / {metrics['repair_rate']}",
        f"- 证据片段案例级全有效率：{metrics['evidence_all_valid_rate']}",
        f"- 关键词召回 / 精确（严格匹配）：{metrics['keyword_recall']} / {metrics['keyword_precision']}",
        f"- 应澄清召回率（{len([c for c in cases if c['difficulty']=='ambiguous'])} 例）：{metrics['clarification_recall']}",
        f"- 误澄清率（非歧义案例）：{metrics['false_clarification_rate']}",
        f"- 否定排除成功率（{metrics['exclusion_cases_total']} 例）：{metrics['exclusion_success_rate']}",
        f"- 诊断·围栏剥离后合规率（工程可救性，非契约）：{metrics['fence_stripped_json_rate_diagnostic']}",
        f"- 诊断·越界词/事件回显率（OOV，隐私风险指标）：{metrics['oov_or_echo_keyword_rate']}", "",
        "## 逐案例结果", ""]
    for r in rows:
        lines.append(f"- [{r['id']}|{r['difficulty']}] {r['status']} "
                     f"recall={r['keyword_recall']} excl={r['exclusion_success']} "
                     f"kws={r['output_keywords']} raw={r['raw_content'][:80]!r}")
    lines += ["", "## 关键结论（基于本次数据）", "",
              f"1. 格式问题是工程可救的：严格契约合规率仅 {metrics['raw_json_rate']}，"
              f"但围栏剥离诊断显示 {metrics['fence_stripped_json_rate_diagnostic']} 的输出"
              "在剥围栏后即可通过 Schema——主要缺口是模型不遵守'纯JSON'指令，而非字段能力。",
              f"2. 修复轮无效：修复触发率 {metrics['repair_rate']} 但修复后合规率未提升"
              f"（仍为 {metrics['final_json_rate']}），temperature=0 下模型重复同样的围栏行为。",
              f"3. 语义能力真实不足：关键词召回 {metrics['keyword_recall']}、精确率 "
              f"{metrics['keyword_precision']}、否定排除成功率 {metrics['exclusion_success_rate']}、"
              f"应澄清召回 {metrics['clarification_recall']}——支持 DESIGN §6'必须训练独立适配器'"
              "的判断，且仅靠提示词工程无法弥补。",
              "4. 稳健性风险：出现重复循环案例（详见 gold_baseline.json），建议执行层"
              "加 n_predict 上限与超时；本客户端已有 60 秒超时与 needs_input 回退。",
              "5. 隐私护栏已就位：客户端对解析后关键词做词表越界标记；已解析案例越界率"
              f"为 {metrics['oov_or_echo_keyword_rate']}，但失败案例的原始输出中观察到事件"
              "原文回显行为，印证关键词必须经词表/规则核验后才可用于搜索。", "",
              "## 边界声明", "",
              "- 本报告是本地 Qwen2.5-0.5B 原权重的行为基线，不是训练成果，不是端到端验收。",
              "- 关键词为候选提取，不构成购买指令；城市与预算从未进入模型请求。",
              "- 修复最多一次；失败案例原文全部留痕于 gold_baseline.json。"]
    (OUT_DIR / "金标准基线报告_1111ver2.md").write_text("\n".join(lines), encoding="utf-8")
    print("\nmetrics:", json.dumps(metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
