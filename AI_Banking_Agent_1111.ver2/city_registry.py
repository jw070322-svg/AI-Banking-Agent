"""城市映射证据登记与强制解析（工作包C §6 + S1.4 修复 R4）。

纪律（S1.4 修复后，全部代码化）：
- **单一强制解析器** `resolve_city_code`：条目形状、来源主机、完整 64 位证据哈希、
  证据文件存在、哈希重算匹配、证据时效、非未来日期、证据内容与城市/代码一致——
  任一不满足 → needs_city_resolution（不猜测、不导航）。
- 时效天数不再默认 None：DEFAULT_MAX_AGE_DAYS=90，显式传入的 None 视为未配置错误。
- 登记 `register_city_mapping`：登记时即要求证据文件存在、哈希可复验、哈希全格式、
  非未来日期；同名城市不同码拒绝自动覆盖。
- 证据内容一致性：证据文件必须同时包含平台码 URL 片段（keyword/{code}/）与城市名。
- 歧义名称以 administrative_region 显式标识。
- build_search_url 主机受限（www.dianping.com），并要求到达结果页后复核城市与关键词
  （该复核由 executor 会话的 search 后置条件承载，registry 只负责出发前门槛）。
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from executor.base import sha256_of

DEFAULT_MAPPING_PATH = Path(__file__).parent / "data" / "city_mappings.json"
ALLOWED_HOST = "www.dianping.com"
DEFAULT_MAX_AGE_DAYS = 90
REQUIRED_MAPPING_FIELDS = ("city_name", "administrative_region", "platform_city_code",
                           "source_url", "evidence_hash", "verified_at")
FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_SOURCE_HOSTS = {"www.dianping.com", "dianping.com", "m.dianping.com"}


class CityMappingError(ValueError):
    """城市映射登记或数据非法。"""


def _now_utc():
    return datetime.now(timezone.utc)


def _validate_entry(entry):
    """条目形状：六必填字段 + 平台码合法 + 哈希全格式 + 主机白名单 + 非未来日期。"""
    if not isinstance(entry, dict):
        raise CityMappingError("映射条目必须是对象")
    missing = [k for k in REQUIRED_MAPPING_FIELDS
               if not isinstance(entry.get(k), str) or not entry[k].strip()]
    if missing:
        raise CityMappingError(f"映射条目缺少必需字段：{missing}（未验证城市码不入库）")
    if not str(entry["platform_city_code"]).isalnum():
        raise CityMappingError(f"平台城市码非法：{entry['platform_city_code']!r}")
    if not FULL_SHA256.match(entry["evidence_hash"]):
        raise CityMappingError(f"证据哈希必须为完整64位十六进制：{entry['evidence_hash']!r}")
    host = (urlparse(entry["source_url"]).hostname or "").lower()
    if host not in ALLOWED_SOURCE_HOSTS:
        raise CityMappingError(f"来源主机不在白名单：{host!r}")
    try:
        verified = date.fromisoformat(entry["verified_at"][:10])
    except ValueError as exc:
        raise CityMappingError(f"verified_at 非法：{exc}") from None
    if verified > _now_utc().date():
        raise CityMappingError(f"verified_at 为未来日期：{entry['verified_at']}")


def _evidence_content_ok(entry, base_dir):
    """证据文件存在 + 哈希重算匹配 + 内容含平台码URL片段与城市名。返回发现或 None。"""
    ref = entry.get("evidence_ref")
    if not ref:
        return "无本地证据文件引用（evidence_ref）；仅会话观察不构成导航依据"
    path = Path(base_dir) / ref
    if not path.is_file():
        return f"证据文件缺失：{ref}"
    actual = sha256_of(path)
    if not actual.startswith(entry["evidence_hash"]):
        return (f"证据哈希不匹配：登记 {entry['evidence_hash'][:16]}，"
                f"实际 {actual[:16]}")
    content = path.read_text(encoding="utf-8", errors="replace")
    code = entry["platform_city_code"]
    if f"keyword/{code}/" not in content:
        return f"证据内容缺少平台码一致性要素（keyword/{code}/）"
    if entry["city_name"] not in content:
        return f"证据内容缺少城市名一致性要素（{entry['city_name']}）"
    return None


def load_city_mappings(path=None):
    path = Path(path) if path else DEFAULT_MAPPING_PATH
    if not path.is_file():
        return {"mappings": []}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    mappings = data.get("mappings") if isinstance(data, dict) else None
    if not isinstance(mappings, list):
        raise CityMappingError("城市映射文件结构非法：缺少 mappings 列表")
    for entry in mappings:
        _validate_entry(entry)
    return {"mappings": mappings}


def register_city_mapping(entry, path=None, base_dir=None):
    """登记新映射：形状校验 + 证据文件当场复验（存在/哈希匹配/内容一致）+
    冲突检查（同名城市不同码拒绝自动覆盖；相同证据拒绝重复登记）。"""
    _validate_entry(entry)
    base = Path(base_dir) if base_dir else Path(__file__).parent
    finding = _evidence_content_ok(entry, base)
    if finding:
        raise CityMappingError(f"登记被拒绝（证据不可复验）：{finding}")
    path = Path(path) if path else DEFAULT_MAPPING_PATH
    existing = load_city_mappings(path)["mappings"]
    same_city = [m for m in existing if m["city_name"] == entry["city_name"]]
    for other in same_city:
        if other["platform_city_code"] == entry["platform_city_code"]:
            if other["evidence_hash"] == entry["evidence_hash"]:
                raise CityMappingError(f"重复登记：{entry['city_name']}="
                                       f"{entry['platform_city_code']} 已存在相同证据")
            continue  # 同码不同证据：允许补充新证据条目
        raise CityMappingError(
            f"城市码冲突：{entry['city_name']} 已登记为 {other['platform_city_code']}，"
            f"新条目为 {entry['platform_city_code']}；需人工重新核实，不自动覆盖")
    existing.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mappings": existing}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {"registered": entry["city_name"], "platform_city_code": entry["platform_city_code"]}


def _age_days(verified_at, now_utc):
    verified = date.fromisoformat(verified_at[:10])
    today = (now_utc or _now_utc()).date()
    return (today - verified).days


def resolve_city_code(city_name, mappings=None, path=None,
                      max_age_days=DEFAULT_MAX_AGE_DAYS, now_utc=None,
                      base_dir=None):
    """S1.4 单一强制解析器：证据存在/哈希复验/内容一致/时效/非未来 全部通过才返回
    resolved；任一不满足 → needs_city_resolution（不猜测、不导航）。
    max_age_days=None 视为未配置错误（评审：freshness limit 默认 None 属缺陷）。"""
    if max_age_days is None:
        raise ValueError("max_age_days 未配置（None）：证据时效必须显式设定")
    mappings = mappings if mappings is not None else load_city_mappings(path)
    matches = [m for m in mappings["mappings"] if m["city_name"] == city_name]
    if not matches:
        return {"status": "needs_city_resolution",
                "reason": f"无已核实映射：{city_name}；不猜测城市码"}
    matches = sorted(matches, key=lambda m: m["verified_at"], reverse=True)
    blockers = []
    chosen = None
    for entry in matches:  # 按最新优先逐条尝试，第一条全通过者胜出
        blockers = []
        try:
            _validate_entry(entry)
        except CityMappingError as exc:
            blockers.append(f"条目非法：{exc}")
            continue
        age = _age_days(entry["verified_at"], now_utc)
        if age < 0:
            blockers.append(f"verified_at 为未来日期：{entry['verified_at']}")
            continue
        if age > max_age_days:
            blockers.append(f"证据过期：{entry['verified_at']} 距今 {age} 天 "
                            f"> 允许 {max_age_days} 天")
            continue
        finding = _evidence_content_ok(entry, base_dir or Path(__file__).parent)
        if finding:
            blockers.append(f"证据不可复验：{finding}")
            continue
        chosen = entry
        break
    if chosen is None:
        return {"status": "needs_city_resolution",
                "reason": "；".join(blockers) or "无可复验映射",
                "attempts": len(matches)}
    return {"status": "resolved", "mapping": chosen, "reason": None}


def verify_city_evidence(mappings=None, path=None, base_dir=None):
    """复验映射证据：证据文件/哈希/内容一致性逐条报告；无本地文件的如实报告。"""
    mappings = mappings if mappings is not None else load_city_mappings(path)
    base = Path(base_dir) if base_dir else Path(__file__).parent
    findings = []
    for entry in mappings["mappings"]:
        finding = _evidence_content_ok(entry, base)
        if finding:
            findings.append({"city_name": entry["city_name"], "status": "unverifiable",
                             "detail": finding})
    return findings


def build_search_url(city_name, keyword, mappings=None, path=None,
                     host=ALLOWED_HOST, max_age_days=DEFAULT_MAX_AGE_DAYS,
                     now_utc=None, base_dir=None):
    """按强制解析结果构造搜索URL（direct_navigation 机制支持）。
    主机受限；证据不可复验时原样返回 needs_city_resolution（导航前停止）。"""
    if host != ALLOWED_HOST:
        raise CityMappingError(f"主机受限：仅允许 {ALLOWED_HOST}，收到 {host!r}")
    resolution = resolve_city_code(city_name, mappings=mappings, path=path,
                                    max_age_days=max_age_days, now_utc=now_utc,
                                    base_dir=base_dir)
    if resolution["status"] != "resolved":
        return resolution
    code = resolution["mapping"]["platform_city_code"]
    return {"status": "ok",
            "url": f"https://{host}/search/keyword/{code}/0_{quote(keyword, safe='')}",
            "mapping": resolution["mapping"],
            "execution_method": "direct_navigation"}
