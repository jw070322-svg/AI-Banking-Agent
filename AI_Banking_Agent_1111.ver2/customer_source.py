"""客户来源适配器（工作包C §6）——显式记录ID读取，本地结构化文件首个适配器。

规则（设计文档 §2/§6 与 2026-11-12 反馈）：
- 只接受显式 record_id + 显式来源配置；禁止遍历文件系统或资料库选客。
- 缺ID → needs_input；查无记录 → not_found；来源内重复ID → duplicate_record；
  配置缺失/路径非法/JSON非法 → source_error。任何情况下不自动换客。
- 测试来源与真实来源强制分开标记（config["kind"]），快照携带 source_kind；
  合成客户不计入真实试点。
- 原始敏感字段只在本地内存/快照中处理，不写入常规运行日志；交接只携带
  customer_ref 与快照指纹，不携带事件原文（由 build_plan 既有脱敏保证）。
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

SUPPORTED_SOURCE_TYPES = ("local_json_file",)
SUPPORTED_KINDS = ("test_fixture", "local_real_file")


def _now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:16]


def _error(status, reason):
    return {"status": status, "reason": reason, "snapshot": None, "fetched_at": _now()}


def get_customer_snapshot(record_id, source_config):
    """显式 record_id → 客户快照。状态机：
    ok / needs_input（ID缺失）/ not_found（查无记录）/ duplicate_record（来源内重复）/
    source_error（配置缺失、路径非法、JSON非法、类型或标记不受支持）。
    本函数不做任何文件系统遍历；只读 source_config["path"] 指向的单一文件。"""
    if not isinstance(record_id, str) or not record_id.strip():
        return _error("needs_input", "缺少显式客户记录ID；不自动选客")
    if not isinstance(source_config, dict):
        return _error("source_error", "来源配置缺失或非法")
    if source_config.get("type") not in SUPPORTED_SOURCE_TYPES:
        return _error("source_error", f"来源类型不受支持：{source_config.get('type')!r}"
                                       f"（支持 {SUPPORTED_SOURCE_TYPES}）")
    if source_config.get("kind") not in SUPPORTED_KINDS:
        return _error("source_error", f"来源标记必须显式为 {SUPPORTED_KINDS} 之一，"
                                       "测试来源与真实来源不得混用")
    path = source_config.get("path")
    if not isinstance(path, (str, Path)):
        return _error("source_error", "来源路径缺失")
    path = Path(path)
    if not path.is_file():
        return _error("source_error", f"来源文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        return _error("source_error", f"来源JSON非法或不可读：{exc}")
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        return _error("source_error", "来源结构非法：缺少 records 列表")
    matches = [r for r in records if isinstance(r, dict) and r.get("record_id") == record_id]
    if not matches:
        return _error("not_found", f"来源中不存在记录：{record_id}；不自动换客")
    if len(matches) > 1:
        return _error("duplicate_record",
                      f"来源内存在 {len(matches)} 条重复 record_id：{record_id}；需人工清理来源")
    record = matches[0]
    missing = [k for k in ("city", "special_event", "budget") if k not in record]
    if missing:
        return _error("source_error", f"记录缺少必需字段：{missing}")
    snapshot = {"customer_ref": record_id,
                "city": record.get("city"),
                "special_event": record.get("special_event"),
                "budget": record.get("budget"),
                "party_size": record.get("party_size"),
                "location_mode": record.get("location_mode", "city_only"),
                "record_flags": {k: record[k] for k in ("synthetic", "test_only")
                                 if k in record}}
    return {"status": "ok", "customer_ref": record_id, "snapshot": snapshot,
            "source_kind": source_config["kind"],
            "source_version": source_config.get("source_version", "unversioned"),
            "snapshot_fingerprint": _fingerprint(snapshot),
            "fetched_at": _now()}


def build_plan_from_snapshot(snapshot_result, workflow_module=None):
    """快照 → 计划：仅接受 status=ok 的快照；计划绑定客户引用与快照指纹，
    供交接与预算版本核对（§4.1/§6 价格与交接绑定当前客户快照）。"""
    if snapshot_result.get("status") != "ok":
        return {"status": snapshot_result.get("status"),
                "reason": snapshot_result.get("reason",
                                              "快照不可用；不自动换客"),
                "plan": None}
    import workflow
    module = workflow_module or workflow
    snapshot = snapshot_result["snapshot"]
    payload = {"city": snapshot["city"], "special_event": snapshot["special_event"],
               "budget": snapshot["budget"], "party_size": snapshot["party_size"],
               "location_mode": snapshot["location_mode"]}
    plan = module.build_plan(payload)
    fingerprint = snapshot_result["snapshot_fingerprint"]
    plan["customer_ref_snapshot"] = (f"{snapshot_result['customer_ref']}"
                                     f"@{snapshot_result['source_version']}:"
                                     f"{fingerprint}")
    plan["customer_snapshot_hash"] = fingerprint
    plan["source_kind"] = snapshot_result["source_kind"]
    return {"status": plan["status"], "plan": plan, "reason": None}
