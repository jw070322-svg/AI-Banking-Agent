"""一键本地回归（Phase 0 加固）：单元测试 + JSON Schema 契约校验 + 词库完整性 + 计划往返。

边界声明：本脚本只做本地确定性检查——不启动浏览器、不调用千问模型、
不是模型评测、不是真实点评端到端测试；结果追加写入 TEST_RESULTS.txt 留痕。
"""
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lexicon import load_lexicon  # noqa: E402
from schema_check import load_schema, validate  # noqa: E402
from workflow import build_plan  # noqa: E402


def check_unittest(report):
    buffer = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern="test_*.py")
    result = unittest.TextTestRunner(stream=buffer, verbosity=2).run(suite)
    ok = result.wasSuccessful()
    report.append(f"[1] 单元测试：{'全部通过' if ok else '存在失败'}"
                  f"（运行 {result.testsRun} 项，失败 {len(result.failures)}，错误 {len(result.errors)}）")
    if not ok:
        report.append(buffer.getvalue())
    return ok


def check_example_customer(report):
    data = json.loads((ROOT / "example_customer.json").read_text(encoding="utf-8-sig"))
    validate(data, load_schema("customer_input.schema.json"))
    report.append("[2] example_customer.json 符合 customer_input 契约")
    return True


def check_lexicon(report):
    lexicon = load_lexicon()
    total = sum(len(c["search_keywords"]) for c in lexicon["categories"])
    report.append(f"[3] 词库完整：{lexicon['lexicon_version']}，"
                  f"{len(lexicon['categories'])} 个触发品类 / {total} 个搜索关键词 / "
                  f"{len(lexicon['negation_prefixes'])} 个否定前缀")
    return True


def check_plan_roundtrip(report):
    data = json.loads((ROOT / "example_customer.json").read_text(encoding="utf-8-sig"))
    plan = build_plan(data)
    validate(plan, load_schema("plan.schema.json"))
    if plan["status"] != "planned" or not plan["keywords"]:
        raise AssertionError("示例客户应产出 planned 状态与非空关键词")
    if plan["live_executed"] is not False or plan["mode"] != "plan_only":
        raise AssertionError("plan_only 纪律被破坏")
    report.append(f"[4] 计划往返：status=planned，keywords={plan['keywords']}，"
                  f"keyword_source={plan['keyword_source']}，negated={plan['negated_keywords']}，"
                  f"review_flags={len(plan['review_flags'])} 项")
    return True


CHECKS = [check_unittest, check_example_customer, check_lexicon, check_plan_roundtrip]


def main():
    report, ok = [], True
    for index, check in enumerate(CHECKS, start=1):
        try:
            ok = check(report) and ok
        except Exception as exc:  # 检查自身异常也如实记录
            ok = False
            report.append(f"[{index}] {check.__name__} 异常：{exc!r}")
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat()
    summary = "全部通过" if ok else "存在失败（未通过项如实记录；不得据此宣称任何未实现目标完成）"
    lines = ["", f"2026-11-12 Phase 0 本地加固检查（{stamp}）",
             "命令：python run_all_checks.py（或 启动1111本地测试.bat）",
             "内容：单元测试 + JSON Schema 契约校验 + 词库完整性 + 计划往返校验",
             f"结果：{summary}",
             *("  " + line for line in report),
             "性质：本地确定性检查；不是模型评测，不是真实点评端到端测试。"]
    text = "\n".join(lines)
    with (ROOT / "TEST_RESULTS.txt").open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
