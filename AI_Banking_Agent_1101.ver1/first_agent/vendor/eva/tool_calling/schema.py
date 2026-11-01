"""A small, dependency-free JSON-Schema subset used by the registry.

Why not Pydantic/jsonschema? The repository is deliberately standard-library
only. This module covers the keywords Module 6 needs: object properties,
required fields, additionalProperties, arrays, enums, bounds, patterns, and a
few deterministic string formats (decimal/date/year-month).

Validation messages intentionally describe the schema, not the caller's value,
so invalid input containing PII never lands in traces or error payloads.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .utils import canonical_json

_MISSING = object()
_DECIMAL_RE = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_YEAR_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


def object_schema(
    properties: dict[str, dict[str, Any]],
    *,
    required: list[str] | tuple[str, ...] | None = None,
    additional_properties: bool | dict[str, Any] = False,
    description: str = "",
    default: Any = _MISSING,
    nullable: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = list(required)
    if description:
        schema["description"] = description
    if default is not _MISSING:
        schema["default"] = default
    if nullable:
        schema["nullable"] = True
    return schema


def array_schema(
    items: dict[str, Any],
    *,
    description: str = "",
    min_items: int | None = None,
    max_items: int | None = None,
    unique_items: bool = False,
    default: Any = _MISSING,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": items}
    if description:
        schema["description"] = description
    if min_items is not None:
        schema["minItems"] = min_items
    if max_items is not None:
        schema["maxItems"] = max_items
    if unique_items:
        schema["uniqueItems"] = True
    if default is not _MISSING:
        schema["default"] = default
    return schema


def string_schema(
    description: str = "",
    *,
    min_length: int | None = None,
    max_length: int | None = None,
    enum: list[str] | tuple[str, ...] | None = None,
    pattern: str | None = None,
    format: str | None = None,
    default: str | None = _MISSING,
    nullable: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if description:
        schema["description"] = description
    if min_length is not None:
        schema["minLength"] = min_length
    if max_length is not None:
        schema["maxLength"] = max_length
    if enum is not None:
        schema["enum"] = list(enum)
    if pattern is not None:
        schema["pattern"] = pattern
    if format is not None:
        schema["format"] = format
    if default is not _MISSING:
        schema["default"] = default
    if nullable:
        schema["nullable"] = True
    return schema


def money_schema(
    description: str = "",
    *,
    default: str | None = _MISSING,
    nullable: bool = False,
) -> dict[str, Any]:
    """Decimal strings avoid binary-float drift for monetary calculations."""
    return string_schema(
        description,
        format="decimal",
        default=default,
        nullable=nullable,
    )


def integer_schema(
    description: str = "",
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    enum: list[int] | tuple[int, ...] | None = None,
    default: int | None = _MISSING,
    nullable: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer"}
    if description:
        schema["description"] = description
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    if enum is not None:
        schema["enum"] = list(enum)
    if default is not _MISSING:
        schema["default"] = default
    if nullable:
        schema["nullable"] = True
    return schema


def number_schema(
    description: str = "",
    *,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
    default: float | int | None = _MISSING,
    nullable: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "number"}
    if description:
        schema["description"] = description
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    if default is not _MISSING:
        schema["default"] = default
    if nullable:
        schema["nullable"] = True
    return schema


def boolean_schema(
    description: str = "",
    *,
    default: bool | None = _MISSING,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "boolean"}
    if description:
        schema["description"] = description
    if default is not _MISSING:
        schema["default"] = default
    return schema


def apply_defaults(value: Any, schema: dict[str, Any]) -> Any:
    """Return a deep-ish copy with object-property defaults filled in."""
    if not isinstance(schema, dict) or not isinstance(value, (dict, list)):
        if schema.get("default", _MISSING) is not _MISSING and value is None:
            return _copy_default(schema["default"])
        return value

    if isinstance(value, dict) and schema.get("type") == "object":
        result = {key: item for key, item in value.items()}
        for key, prop_schema in schema.get("properties", {}).items():
            if key not in result and "default" in prop_schema:
                result[key] = _copy_default(prop_schema["default"])
            elif key in result:
                result[key] = apply_defaults(result[key], prop_schema)
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            for key in result:
                if key not in schema.get("properties", {}):
                    result[key] = apply_defaults(result[key], additional)
        return result

    if isinstance(value, list) and schema.get("type") == "array":
        item_schema = schema.get("items", {})
        return [apply_defaults(item, item_schema) for item in value]

    return value


def _copy_default(value: Any) -> Any:
    # JSON round-trip prevents shared mutable defaults.
    import json

    return json.loads(json.dumps(value))


def validate_instance(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "$",
) -> list[ValidationIssue]:
    """Validate a Python value against the supported JSON-schema subset."""
    if not isinstance(schema, dict):
        return [ValidationIssue(path, "schema_error", "schema must be an object")]

    if value is None:
        if schema.get("nullable"):
            return []
        return [
            ValidationIssue(path, "null_not_allowed", "value must not be null")
        ]

    schema_type = schema.get("type")
    if schema_type is None:
        return []
    if schema_type not in {
        "object",
        "array",
        "string",
        "integer",
        "number",
        "boolean",
    }:
        return [
            ValidationIssue(
                path, "schema_error", f"unsupported schema type: {schema_type}"
            )
        ]

    issues: list[ValidationIssue] = []
    if not _matches_type(value, schema_type):
        issues.append(
            ValidationIssue(path, "type_mismatch", f"expected {schema_type}")
        )
        return issues

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        issues.append(
            ValidationIssue(path, "enum_mismatch", "value is not an allowed option")
        )

    if schema_type == "object":
        issues.extend(_validate_object(value, schema, path))
    elif schema_type == "array":
        issues.extend(_validate_array(value, schema, path))
    elif schema_type == "string":
        issues.extend(_validate_string(value, schema, path))
    elif schema_type in {"integer", "number"}:
        issues.extend(_validate_number(value, schema, path))

    return issues


def _matches_type(value: Any, schema_type: str) -> bool:
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return (
            isinstance(value, (int, float, Decimal))
            and not isinstance(value, bool)
        )
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    return False


def _validate_object(
    value: dict[str, Any], schema: dict[str, Any], path: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for name in required:
        if name not in value:
            issues.append(
                ValidationIssue(
                    f"{path}.{name}", "missing_required", "required field is missing"
                )
            )

    additional = schema.get("additionalProperties", False)
    for key, item in value.items():
        child_path = f"{path}.{key}"
        if not isinstance(key, str):
            issues.append(
                ValidationIssue(path, "invalid_key", "object keys must be strings")
            )
            continue
        if key in properties:
            issues.extend(validate_instance(item, properties[key], path=child_path))
        elif additional is False:
            issues.append(
                ValidationIssue(
                    child_path,
                    "unknown_field",
                    "field is not defined in the input schema",
                )
            )
        elif isinstance(additional, dict):
            issues.extend(validate_instance(item, additional, path=child_path))
    return issues


def _validate_array(
    value: list[Any], schema: dict[str, Any], path: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    min_items = schema.get("minItems")
    max_items = schema.get("maxItems")
    if min_items is not None and len(value) < min_items:
        issues.append(
            ValidationIssue(
                path, "too_few_items", f"at least {min_items} item(s) required"
            )
        )
    if max_items is not None and len(value) > max_items:
        issues.append(
            ValidationIssue(
                path, "too_many_items", f"at most {max_items} item(s) allowed"
            )
        )
    item_schema = schema.get("items", {})
    for index, item in enumerate(value):
        issues.extend(
            validate_instance(item, item_schema, path=f"{path}[{index}]")
        )
    if schema.get("uniqueItems"):
        seen: set[str] = set()
        for index, item in enumerate(value):
            fingerprint = canonical_json(item)
            if fingerprint in seen:
                issues.append(
                    ValidationIssue(
                        f"{path}[{index}]",
                        "duplicate_item",
                        "items must be unique",
                    )
                )
            seen.add(fingerprint)
    return issues


def _validate_string(
    value: str, schema: dict[str, Any], path: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(value) < schema.get("minLength", 0):
        issues.append(
            ValidationIssue(path, "too_short", "string is shorter than allowed")
        )
    if schema.get("maxLength") is not None and len(value) > schema["maxLength"]:
        issues.append(
            ValidationIssue(path, "too_long", "string is longer than allowed")
        )
    pattern = schema.get("pattern")
    if pattern is not None and re.search(pattern, value) is None:
        issues.append(
            ValidationIssue(path, "pattern_mismatch", "string does not match pattern")
        )

    value_format = schema.get("format")
    if value_format == "decimal":
        if _DECIMAL_RE.fullmatch(value) is None:
            issues.append(
                ValidationIssue(
                    path,
                    "invalid_decimal",
                    "expected a plain decimal string such as 100.00",
                )
            )
            return issues
        try:
            number = Decimal(value)
            if not number.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            issues.append(
                ValidationIssue(path, "invalid_decimal", "decimal is not finite")
            )
    elif value_format == "date":
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            issues.append(
                ValidationIssue(path, "invalid_date", "expected YYYY-MM-DD")
            )
    elif value_format == "year-month":
        if _YEAR_MONTH_RE.fullmatch(value) is None:
            issues.append(
                ValidationIssue(path, "invalid_month", "expected YYYY-MM")
            )
    return issues


def _validate_number(
    value: int | float | Decimal, schema: dict[str, Any], path: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if isinstance(value, float) and not math.isfinite(value):
        return [ValidationIssue(path, "not_finite", "number must be finite")]
    number = Decimal(str(value))
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is not None and number < Decimal(str(minimum)):
        issues.append(
            ValidationIssue(
                path, "below_minimum", f"value must be >= {minimum}"
            )
        )
    if maximum is not None and number > Decimal(str(maximum)):
        issues.append(
            ValidationIssue(
                path, "above_maximum", f"value must be <= {maximum}"
            )
        )
    return issues


def issues_to_dicts(issues: list[ValidationIssue]) -> list[dict[str, str]]:
    return [issue.to_dict() for issue in issues]
