"""受限 JSON Schema 校验器（仅标准库）。

支持关键字：type（含 [.., "null"]）、required、properties、items、enum、const、
minItems、maxItems、minimum、maximum、pattern、additionalProperties(false)。
刻意不做 $ref/oneOf/allOf 等完整 JSON Schema 能力；schemas/ 下契约保持在此子集内。
load_schema 结果带缓存，契约在运行期视为只读，调用方不得修改返回对象。
"""
import json
import re
from functools import lru_cache
from pathlib import Path

SCHEMA_DIR = Path(__file__).parent / "schemas"


class SchemaValidationError(ValueError):
    """实例不符合契约。"""


@lru_cache(maxsize=None)
def load_schema(name):
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


_TYPES = {"object": dict, "array": list, "string": str,
          "integer": int, "number": (int, float), "boolean": bool, "null": type(None)}


def _type_ok(value, names):
    for name in names:
        expected = _TYPES.get(name)
        if expected is None:
            continue
        if isinstance(value, expected):
            if name in ("integer", "number") and isinstance(value, bool):
                continue  # 布尔不是数值
            return True
    return False


def validate(instance, schema, path="$"):
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not _type_ok(instance, names):
            raise SchemaValidationError(f"{path}：类型需为 {names}")
    if "const" in schema and instance != schema["const"]:
        raise SchemaValidationError(f"{path}：需等于 {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaValidationError(f"{path}：不在允许枚举内")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                raise SchemaValidationError(f"{path}：缺少必需字段 {key}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                validate(value, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise SchemaValidationError(f"{path}：出现契约外字段 {key}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise SchemaValidationError(f"{path}：元素数量少于 {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise SchemaValidationError(f"{path}：元素数量超过 {schema['maxItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for index, element in enumerate(instance):
                validate(element, item_schema, f"{path}[{index}]")
    if isinstance(instance, str) and "pattern" in schema:
        if not re.search(schema["pattern"], instance):
            raise SchemaValidationError(f"{path}：不匹配模式 {schema['pattern']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise SchemaValidationError(f"{path}：小于最小值 {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            raise SchemaValidationError(f"{path}：大于最大值 {schema['maximum']}")
