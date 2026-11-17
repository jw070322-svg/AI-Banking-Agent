"""工作包C 合成干跑演示（DRY-RUN）。

边界声明（重要）：
- 本演练全程使用 data/customer_fixtures/test_customers.json 的合成客户，
  合成不计真实；本演练不计入设计文档 §6 的 20 次真实试点。
- 未遍历选客：客户由显式 record_id 指定（c-test-001/002/003 为合成fixture）。
- 真实客户来源未确定，真实试点保持阻塞（§6：20次、至少2个有证据城市）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from city_registry import build_search_url, resolve_city_code, verify_city_evidence
from customer_source import build_plan_from_snapshot, get_customer_snapshot


def main():
    print("== 工作包C 合成干跑（非试点；合成fixture；不计入20次真实试点）==\n")

    # 1) 显式ID读取 + 计划接线（c-test-001：正常路径）
    snapshot = get_customer_snapshot("c-test-001",
                                     {"type": "local_json_file", "kind": "test_fixture",
                                      "path": ROOT / "data/customer_fixtures/test_customers.json",
                                      "source_version": "2026-11-12"})
    wired = build_plan_from_snapshot(snapshot)
    plan = wired["plan"]
    print(f"[1] c-test-001 → status={snapshot['status']}，计划={wired['status']}，"
          f"城市={plan['city']}，预算指纹={plan['budget_fingerprint']}，"
          f"绑定={plan['customer_ref_snapshot']}")

    # 2) 口径缺失 → needs_input（不推定）
    missing_basis = build_plan_from_snapshot(get_customer_snapshot(
        "c-test-002", {"type": "local_json_file", "kind": "test_fixture",
                        "path": ROOT / "data/customer_fixtures/test_customers.json"}))
    print(f"[2] c-test-002 → status={missing_basis['status']}，"
          f"issues={missing_basis['plan']['issues']}")

    # 3) 城市映射：已核实杭州=3；未登记城市不猜测
    hangzhou = resolve_city_code("杭州")
    zhuhai = resolve_city_code("珠海")
    print(f"[3] 杭州 → {hangzhou['status']}（码={hangzhou['mapping']['platform_city_code']}，"
          f"证据={hangzhou['mapping']['evidence_ref']}）；"
          f"珠海 → {zhuhai['status']}（{zhuhai['reason']}）")

    # 4) 已证实URL规律的直导航构造
    url = build_search_url("杭州", "生日餐厅")
    print(f"[4] 构造URL：{url['url']}（机制={url['execution_method']}）")

    # 5) 证据复验
    findings = verify_city_evidence()
    print(f"[5] 证据复验发现：{findings or '无（哈希全部匹配）'}")

    print("\n边界：客户为合成fixture；真实客户来源未确定，真实试点保持阻塞；"
          "本演练不产生任何完成度声明。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
