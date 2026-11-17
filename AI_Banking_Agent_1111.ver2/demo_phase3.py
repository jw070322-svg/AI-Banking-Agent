"""Phase 3 端到端交接样例：合成客户 + 2026-11-12 真实观测人均价 + run4 真实执行日志。

边界声明：客户为合成样例；餐厅人均价为站点展示参考价（不保证结算）；
蛋糕价为合成占位（example.com）；组合验证是本地逻辑演示，
不是真实端到端验收，不构成购买指令。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schema_check import load_schema, validate  # noqa: E402
from workflow import allocate_budget, build_plan, filter_candidates, write_handoff  # noqa: E402


def main():
    customer = json.loads((ROOT / "example_customer.json").read_text(encoding="utf-8-sig"))
    plan = build_plan(customer)
    quotes = json.loads((ROOT / "data" / "observed_quotes_20261112.json").read_text(encoding="utf-8-sig"))
    cake = {"id": "synthetic-cake-1", "name": "合成蛋糕报价（占位，example.com）",
            "price_min": "50", "price_max": "80", "currency": "CNY", "basis": "total",
            "price_kind": "listed", "source_url": "https://example.com/synthetic-cake-quote",
            "observed_at": "2026-11-12", "synthetic": True}
    budget, party = plan["budget"], plan["party_size"]

    restaurant_filter = filter_candidates(quotes["items"], budget, party)
    combo = allocate_budget({"餐厅": quotes["items"], "蛋糕": [cake]}, budget,
                            party_size=party, known_surcharges=[])

    run_log = ROOT / "reports" / "sessions" / "20261112-011106-8e0c06fb" / "run.jsonl"
    out = write_handoff(plan, ROOT / "reports" / "phase3", execution_log=run_log)

    (out / "combination.json").write_text(
        json.dumps({"synthetic_customer": True,
                    "observed_prices_note": quotes["note"],
                    "restaurant_filter": restaurant_filter,
                    "combination": combo},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    doc = json.loads((out / "handoff.json").read_text(encoding="utf-8"))
    doc["execution"]["attachments"].append({"name": "combination.json", "path": "combination.json"})
    validate(doc, load_schema("plan.schema.json"))
    (out / "handoff.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    chosen = combo["combination"]["餐厅"]
    md = (out / "handoff.md").read_text(encoding="utf-8")
    md += ("\n\n## 组合验证（Phase 3 样例，本地逻辑演示）\n"
           f"- 判定：{combo['verdict']}（最优 {combo['best_case_cents'] / 100} 元 / "
           f"最坏 {combo['worst_case_cents'] / 100} 元，预算上限 {combo['budget_max_cents'] / 100} 元）\n"
           f"- 所选组合：餐厅={chosen['name']}（人均参考价 {chosen['price_max_cents'] / 100} 元×{party}），"
           "蛋糕=合成占位报价 50–80 元\n"
           f"- 单品类筛选：{combo['per_category']['餐厅']['candidates']} 个候选 / "
           f"{combo['per_category']['餐厅']['excluded']} 个超界（淀·sediment 172×4=688 超 600）\n"
           "- 边界：客户合成；蛋糕价合成占位；餐厅价为页面参考价不保证结算；不构成购买指令\n")
    (out / "handoff.md").write_text(md, encoding="utf-8")

    print(json.dumps({"handoff_dir": str(out), "verdict": combo["verdict"],
                      "best_yuan": combo["best_case_cents"] / 100,
                      "worst_yuan": combo["worst_case_cents"] / 100,
                      "chosen_restaurant": chosen["name"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
