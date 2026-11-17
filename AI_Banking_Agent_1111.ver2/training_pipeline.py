"""Phase 4 轨迹采集脚手架（DESIGN §6，R8）。

数据流：轨迹进入隔离候选库 → 脱敏扫描（命中 PII 拒收进隔离区）→ 人工审核
（approved/rejected + 原因）→ 按（客户引用×事件模板）分组防泄漏划分 →
仅导出 approved 且 split=train 的记录为 Qwen messages 格式。

纪律（代码化）：
- 未审核轨迹不得训练（导出只认 reviewed+approved+train）。
- synthetic/observed 强制标签，导出清单分开计数，不混报采集数量。
- 脱敏扫描命中手机号/身份证/邮箱即进隔离区，不进入候选库。
- 本脚手架只做存储/审核/划分/导出；训练本身属于 Phase 5，仅完成日志记录不算训练完成。
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from schema_check import SchemaValidationError, load_schema, validate  # noqa: E402
from workflow import now  # noqa: E402

BASE_DIR = Path(__file__).parent / "data" / "trajectories"
PII_PATTERNS = {
    "phone_cn": re.compile(r"1[3-9]\d{9}"),
    "id_card_cn": re.compile(r"\d{17}[\dXx]"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


def scan_privacy(record):
    """扫描记录全部字符串字段中的 PII；返回 [{field, kind}]。"""
    findings = []

    def walk(value, field):
        if isinstance(value, str):
            for kind, pattern in PII_PATTERNS.items():
                if pattern.search(value):
                    findings.append({"field": field, "kind": kind})
        elif isinstance(value, dict):
            for key, sub in value.items():
                walk(sub, f"{field}.{key}")
        elif isinstance(value, list):
            for index, sub in enumerate(value):
                walk(sub, f"{field}[{index}]")

    walk(record, "$")
    return findings


def _dir(kind):
    target = BASE_DIR / kind
    target.mkdir(parents=True, exist_ok=True)
    return target


def add_trajectory(record, base_dir=None):
    """新增轨迹：契约校验 + 模型输出契约校验 + 脱敏扫描。
    通过 → candidate/；命中 PII → quarantine/（附扫描结果），不进候选库。"""
    base = Path(base_dir) if base_dir else BASE_DIR
    try:
        validate(record, load_schema("trajectory.schema.json"))
    except SchemaValidationError as exc:
        raise ValueError(f"轨迹不符合契约，拒绝入库：{exc}") from None
    output = record.get("model_output")
    if output is not None:
        try:
            validate(output, load_schema("qwen_output.schema.json"))
        except SchemaValidationError as exc:
            raise ValueError(f"model_output 不符合 qwen_output 契约：{exc}") from None
    findings = scan_privacy(record)
    record_id = record["record_id"]
    if findings:
        target = base / "quarantine" if base == BASE_DIR else base / "quarantine"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{record_id}.json").write_text(
            json.dumps({"record": record, "privacy_findings": findings},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "quarantined", "record_id": record_id, "findings": findings}
    target = base / "candidate"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{record_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "candidate", "record_id": record_id, "findings": []}


def review_trajectory(record_id, decision, reason, base_dir=None):
    """人工审核：candidate → reviewed，写 review_status 与原因。"""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision 只允许 approved/rejected")
    base = Path(base_dir) if base_dir else BASE_DIR
    source = base / "candidate" / f"{record_id}.json"
    if not source.is_file():
        raise FileNotFoundError(f"候选库中不存在轨迹：{record_id}")
    record = json.loads(source.read_text(encoding="utf-8"))
    record["review_status"] = decision
    record["notes"] = ((record.get("notes") or "") + f" | 审核({decision})：{reason}").strip(" |")
    target = base / "reviewed"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{record_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    source.unlink()
    return {"record_id": record_id, "review_status": decision}


def _group_key(record):
    return (record.get("customer_ref") or "no-ref",
            record.get("event_template") or "no-template")


def _split_for(group_key, seed):
    digest = int(hashlib.md5(f"{group_key}:{seed}".encode("utf-8")).hexdigest(), 16) % 100
    if digest < 70:
        return "train"
    if digest < 85:
        return "validation"
    return "test"


def split_reviewed(base_dir=None, seed=20261112):
    """按（客户引用×事件模板）分组划分 train/validation/test，防组间泄漏。
    只处理 approved；pending/rejected 不划分。"""
    base = Path(base_dir) if base_dir else BASE_DIR
    reviewed = base / "reviewed"
    if not reviewed.is_dir():
        return {"assigned": 0, "groups": 0}
    groups = {}
    for path in sorted(reviewed.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("review_status") != "approved":
            continue
        groups.setdefault(_group_key(record), []).append(path)
    assigned = 0
    for group_key, paths in groups.items():
        split = _split_for(group_key, seed)
        for path in paths:
            record = json.loads(path.read_text(encoding="utf-8"))
            record["split"] = split
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            assigned += 1
    return {"assigned": assigned, "groups": len(groups)}


def export_messages(base_dir=None, out_name=None):
    """导出 Qwen messages 格式：仅 reviewed+approved+split=train。
    synthetic/observed 在清单中分开计数，不混报。"""
    base = Path(base_dir) if base_dir else BASE_DIR
    reviewed = base / "reviewed"
    out_dir = base / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    from qwen_client import SYSTEM_PROMPT
    lines, manifest = [], {"train": 0, "validation": 0, "test": 0,
                           "synthetic": 0, "observed": 0, "skipped_not_train": 0}
    for path in sorted((reviewed or []).glob("*.json")) if reviewed.is_dir() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("review_status") != "approved":
            continue
        if record.get("split") != "train":
            manifest["skipped_not_train"] += 1
            continue
        output = record.get("model_output")
        if output is None:
            continue
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "客户特殊事件描述：" + (record.get("input_summary") or "")},
                    {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}]
        lines.append(json.dumps({"record_id": record["record_id"],
                                 "source_kind": record["source_kind"],
                                 "messages": messages}, ensure_ascii=False))
        manifest["train"] += 1
        manifest[record["source_kind"]] = manifest.get(record["source_kind"], 0) + 1
    name = out_name or "messages_train.jsonl"
    (out_dir / name).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (out_dir / "manifest.json").write_text(
        json.dumps({"exported_at_file": name, **manifest,
                    "note": "未审核轨迹不得训练；本清单 synthetic/observed 分开计数"}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {"exported": manifest["train"], "manifest": manifest, "path": str(out_dir / name)}


def status(base_dir=None):
    base = Path(base_dir) if base_dir else BASE_DIR
    result = {}
    for kind in ("candidate", "reviewed", "quarantine"):
        target = base / kind
        result[kind] = len(list(target.glob("*.json"))) if target.is_dir() else 0
    return result


# ---------------------------------------------------------------------------
# 工作包B（§5）：trajectory v2 —— gold标签、关联分量隔离、三集导出
# ---------------------------------------------------------------------------

V2_GROUP_FIELDS = ("customer_group", "template_family", "duplicate_cluster")


def add_trajectory_v2(record, base_dir=None):
    """v2 入库：trajectory_v2 契约 + model_output/gold_output 各自过 qwen_output
    契约（gold 是训练标签，预测只是预测）+ 脱敏扫描。"""
    base = Path(base_dir) if base_dir else BASE_DIR
    try:
        validate(record, load_schema("trajectory_v2.schema.json"))
    except SchemaValidationError as exc:
        raise ValueError(f"v2 轨迹不符合契约，拒绝入库：{exc}") from None
    for label, output in (("model_output", record.get("model_output")),
                          ("gold_output", record.get("gold_output"))):
        if output is not None:
            try:
                validate(output, load_schema("qwen_output.schema.json"))
            except SchemaValidationError as exc:
                raise ValueError(f"{label} 不符合 qwen_output 契约：{exc}") from None
    findings = scan_privacy(record)
    record_id = record["record_id"]
    if findings:
        target = base / "quarantine"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{record_id}.json").write_text(
            json.dumps({"record": record, "privacy_findings": findings},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "quarantined", "record_id": record_id, "findings": findings}
    target = base / "candidate"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{record_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "candidate", "record_id": record_id, "findings": []}


def migrate_v1_to_v2(record):
    """v1 → v2 显式迁移（§10）：缺分组字段标 unknown；时间/审核/证据字段留空
    不补造；split 清空待 v2 重划分。返回 (v2记录, 迁移报告)。"""
    validate(record, load_schema("trajectory.schema.json"))
    v2 = {k: v for k, v in record.items()}
    v2["schema_version"] = 2
    changes = []
    for field, value in (("customer_group", "unknown"), ("template_family", "unknown"),
                         ("duplicate_cluster", "unknown")):
        v2[field] = value
        changes.append(f"{field}={value}")
    for field in ("run_id", "reviewer_ref", "reviewed_at", "review_reason",
                  "gold_output", "evidence_manifest"):
        v2[field] = None
        changes.append(f"{field}=null(不补造)")
    v2["split"] = None
    changes.append("split=null(待v2重划分)")
    input_sha = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False)
                               .encode("utf-8")).hexdigest()
    output_sha = hashlib.sha256(json.dumps(v2, sort_keys=True, ensure_ascii=False)
                                .encode("utf-8")).hexdigest()
    report = {"input_sha256": input_sha, "output_sha256": output_sha,
              "changes": changes, "record_id": record["record_id"]}
    return v2, report


def review_trajectory_v2(record_id, decision, reason, reviewer_ref, base_dir=None):
    """v2 审核：写 review_status/reviewer_ref/reviewed_at/review_reason（§5 元数据）。"""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision 只允许 approved/rejected")
    if not reviewer_ref:
        raise ValueError("v2 审核必须记录 reviewer_ref（拒绝用模型自评代替人工审核）")
    base = Path(base_dir) if base_dir else BASE_DIR
    source = base / "candidate" / f"{record_id}.json"
    if not source.is_file():
        raise FileNotFoundError(f"候选库中不存在轨迹：{record_id}")
    record = json.loads(source.read_text(encoding="utf-8"))
    record["review_status"] = decision
    record["reviewer_ref"] = reviewer_ref
    record["reviewed_at"] = now()
    record["review_reason"] = reason
    target = base / "reviewed"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{record_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    source.unlink()
    return {"record_id": record_id, "review_status": decision,
            "reviewer_ref": reviewer_ref}


def _connected_components(records, group_fields):
    """按关联字段构图（§5.1）：任一字段相同即连边；返回 (component_id → [record])。
    关联字段全缺失（None/'unknown'）的记录不参与图，进入 needs_grouping。"""
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    node_ids = [r["record_id"] for r in records]
    for node in node_ids:
        parent.setdefault(node, node)
    for field in group_fields:
        buckets = {}
        for r in records:
            value = r.get(field)
            if value and value != "unknown":
                buckets.setdefault(value, []).append(r["record_id"])
        for _, members in buckets.items():
            for other in members[1:]:
                union(members[0], other)
    components = {}
    for r in records:
        components.setdefault(find(r["record_id"]), []).append(r)
    return components


def split_reviewed_v2(base_dir=None, seed=20261112):
    """v2 防泄漏划分（§5.1）：关联分量整体进同一数据集；缺分组标识进入
    needs_grouping 不默认共用占位符；输出 split_manifest（含交集检查与输入哈希）。"""
    base = Path(base_dir) if base_dir else BASE_DIR
    reviewed = base / "reviewed"
    if not reviewed.is_dir():
        return {"assigned": 0, "needs_grouping": 0, "components": 0}
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(reviewed.glob("*.json"))]
    approved = [r for r in records if r.get("review_status") == "approved"]
    grouped = [r for r in approved if any(
        r.get(f) and r.get(f) != "unknown" for f in V2_GROUP_FIELDS)]
    needs_grouping = [r for r in approved if r not in grouped]
    components = _connected_components(grouped, V2_GROUP_FIELDS)
    assigned = 0
    manifest_rows = []
    for component_id, members in components.items():
        split = _split_for(component_id, seed)
        for record in members:
            record["split"] = split
            assigned += 1
            manifest_rows.append({"record_id": record["record_id"],
                                   "group_id": f"component-{component_id[:8]}",
                                   "split": split,
                                   "source_kind": record["source_kind"]})
    for record in grouped:
        (reviewed / f"{record['record_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    for record in needs_grouping:
        record["split"] = "needs_grouping"
        (reviewed / f"{record['record_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_rows.append({"record_id": record["record_id"], "group_id": None,
                              "split": "needs_grouping",
                              "source_kind": record["source_kind"]})
    splits = {"train": 0, "validation": 0, "test": 0, "needs_grouping": 0}
    for row in manifest_rows:
        splits[row["split"]] += 1
    sources = {}
    for row in manifest_rows:
        sources[row["source_kind"]] = sources.get(row["source_kind"], 0) + 1
    split_sets = {name: {r["record_id"] for r in manifest_rows if r["split"] == name}
                  for name in ("train", "validation", "test")}
    intersection_check = all(
        not (split_sets[a] & split_sets[b])
        for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")))
    manifest = {"schema_version": "2", "seed": seed,
                "records": manifest_rows, "counts": splits, "sources": sources,
                "components": len(components),
                "intersection_check": "no_leakage" if intersection_check else "LEAK_DETECTED",
                "input_hashes": {r["record_id"]: hashlib.sha256(
                    json.dumps(r, sort_keys=True, ensure_ascii=False)
                    .encode("utf-8")).hexdigest()[:16] for r in grouped + needs_grouping},
                "note": "分量整体分配；巨型分量或覆盖不足时须报告，不为凑比例拆分关联记录"}
    out_dir = base / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "split_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"assigned": assigned, "needs_grouping": len(needs_grouping),
            "components": len(components), "manifest": manifest}


def export_messages_v2(base_dir=None, out_name=None):
    """v2 导出（§5）：仅 approved+train 且 gold_output 通过契约的训练标签导出；
    预测（model_output）不作标签；failure_model 未纠正（无 gold）拒绝导出并单独计数。"""
    base = Path(base_dir) if base_dir else BASE_DIR
    reviewed = base / "reviewed"
    out_dir = base / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    from qwen_client import SYSTEM_PROMPT
    lines = []
    manifest = {"train": 0, "skipped_not_train": 0, "skipped_no_gold": 0,
                "skipped_uncorrected_model_error": 0, "skipped_rejected_or_pending": 0,
                "synthetic": 0, "observed": 0}
    for path in sorted(reviewed.glob("*.json")) if reviewed.is_dir() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("review_status") != "approved":
            manifest["skipped_rejected_or_pending"] += 1
            continue
        if record.get("split") != "train":
            manifest["skipped_not_train"] += 1
            continue
        gold = record.get("gold_output")
        if gold is None:
            if record.get("correction_label") == "failure_model":
                manifest["skipped_uncorrected_model_error"] += 1
            else:
                manifest["skipped_no_gold"] += 1
            continue
        try:
            validate(gold, load_schema("qwen_output.schema.json"))
        except SchemaValidationError:
            manifest["skipped_no_gold"] += 1
            continue
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "客户特殊事件描述：" + (record.get("input_summary") or "")},
                    {"role": "assistant", "content": json.dumps(gold, ensure_ascii=False)}]
        lines.append(json.dumps({"record_id": record["record_id"],
                                 "source_kind": record["source_kind"],
                                 "correction_label": record.get("correction_label"),
                                 "messages": messages}, ensure_ascii=False))
        manifest["train"] += 1
        manifest[record["source_kind"]] = manifest.get(record["source_kind"], 0) + 1
    name = out_name or "messages_train_v2.jsonl"
    (out_dir / name).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (out_dir / "manifest_v2.json").write_text(
        json.dumps({"exported_file": name, **manifest,
                    "note": "训练标签=人工审核gold_output；未审核/未纠正/非train一律不导出"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return {"exported": manifest["train"], "manifest": manifest,
            "path": str(out_dir / name)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("file", type=Path)

    p_review = sub.add_parser("review")
    p_review.add_argument("record_id")
    p_review.add_argument("--decision", required=True, choices=["approved", "rejected"])
    p_review.add_argument("--reason", required=True)

    p_split = sub.add_parser("split")
    p_split.add_argument("--seed", type=int, default=20261112)

    sub.add_parser("export")
    sub.add_parser("status")

    p_add2 = sub.add_parser("add2")
    p_add2.add_argument("file", type=Path)

    p_migrate = sub.add_parser("migrate")
    p_migrate.add_argument("file", type=Path)

    p_review2 = sub.add_parser("review2")
    p_review2.add_argument("record_id")
    p_review2.add_argument("--decision", required=True, choices=["approved", "rejected"])
    p_review2.add_argument("--reason", required=True)
    p_review2.add_argument("--reviewer", required=True)

    p_split2 = sub.add_parser("split2")
    p_split2.add_argument("--seed", type=int, default=20261112)

    sub.add_parser("export2")

    args = parser.parse_args()
    if args.command == "add":
        record = json.loads(args.file.read_text(encoding="utf-8-sig"))
        print(json.dumps(add_trajectory(record), ensure_ascii=False))
    elif args.command == "review":
        print(json.dumps(review_trajectory(args.record_id, args.decision, args.reason),
                         ensure_ascii=False))
    elif args.command == "split":
        print(json.dumps(split_reviewed(seed=args.seed), ensure_ascii=False))
    elif args.command == "export":
        print(json.dumps(export_messages(), ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(status(), ensure_ascii=False))
    elif args.command == "add2":
        record = json.loads(args.file.read_text(encoding="utf-8-sig"))
        print(json.dumps(add_trajectory_v2(record), ensure_ascii=False))
    elif args.command == "migrate":
        record = json.loads(args.file.read_text(encoding="utf-8-sig"))
        v2, report = migrate_v1_to_v2(record)
        print(json.dumps({"record": v2, "migration_report": report}, ensure_ascii=False))
    elif args.command == "review2":
        print(json.dumps(review_trajectory_v2(args.record_id, args.decision,
                                              args.reason, args.reviewer),
                         ensure_ascii=False))
    elif args.command == "split2":
        print(json.dumps(split_reviewed_v2(seed=args.seed), ensure_ascii=False))
    elif args.command == "export2":
        print(json.dumps(export_messages_v2(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
