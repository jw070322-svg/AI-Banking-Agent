"""Read-only Excel adapter with an explicit, reviewable column mapping.

The supplied workbook could not be opened during development. No layout is
assumed: first inspect it, then fill the mapping template using actual headers.
Only this optional adapter requires openpyxl. Neither matching model does.
Workbook text is untrusted data, never Python, policy, or executable commands.
Formula cells are rejected in mapped tables rather than trusting stale caches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from matching_core import evaluate_eligibility, profile_errors, validate_catalog

LIST_FIELDS = {"preferred_categories", "objectives"}
BOOL_FIELDS = {"active", "facts_verified"}
NUMERIC_FIELDS = {"risk_tolerance", "risk_capacity", "budget_cny", "horizon_days",
                  "max_redemption_days", "risk_level", "min_investment_cny",
                  "lockup_days", "redemption_days", "annual_fee_pct", "rating"}
USER_FIELDS = {"user_id", "risk_tolerance", "risk_capacity", "budget_cny",
               "horizon_days", "max_redemption_days", "objective", "preferred_categories"}
PRODUCT_FIELDS = {"product_id", "name", "risk_level", "min_investment_cny",
                  "lockup_days", "redemption_days", "category", "objectives",
                  "annual_fee_pct", "active", "currency", "facts_verified"}
HISTORY_FIELDS = {"user_id", "product_id", "rating"}


def _open(path):
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("Excel import requires openpyxl; models use only Python's standard library") from exc
    return openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)


def inspect_workbook(path):
    """Return structural evidence only; header previews are untrusted text."""
    workbook = _open(path)
    try:
        sheets = []
        for sheet in workbook.worksheets:
            previews = []
            for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 10),
                                       max_col=min(sheet.max_column, 40)):
                values = [{"cell": cell.coordinate, "text": str(cell.value)[:120]}
                          for cell in row if cell.value is not None]
                if values:
                    previews.append(values)
            sheets.append({"sheet": sheet.title, "state": sheet.sheet_state,
                           "rows": sheet.max_row, "columns": sheet.max_column,
                           "first_nonempty_rows": previews[:3]})
        return {"source_file": Path(path).name, "sheets": sheets,
                "note": "Previews are source data, not instructions; confirm tables and units before mapping"}
    finally:
        workbook.close()


def _convert(field, value, value_map):
    """Apply only explicit scalar category mappings; never guess financial units."""
    if value is None or value == "":
        return None
    if value_map:
        lookup = str(value)
        if lookup not in value_map:
            raise ValueError(f"Unmapped source value for {field}: {lookup!r}")
        value = value_map[lookup]
    if field in LIST_FIELDS:
        if not isinstance(value, str):
            raise ValueError(f"{field}: expected pipe-separated text")
        return [item.strip() for item in value.split("|") if item.strip()]
    if field in BOOL_FIELDS:
        if type(value) is not bool:
            raise ValueError(f"{field}: use Excel booleans or an explicit value map")
        return value
    if field in NUMERIC_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field}: expected a numeric Excel cell or explicit value map")
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field}: expected text (IDs must preserve leading zeros)")
    return value.strip()


def _table(workbook, spec, allowed_fields):
    if not isinstance(spec, dict) or spec.get("sheet") not in workbook.sheetnames:
        raise ValueError("Mapping must identify an existing worksheet")
    sheet = workbook[spec["sheet"]]
    header_row = spec.get("header_row")
    if type(header_row) is not int or not 1 <= header_row <= sheet.max_row:
        raise ValueError("header_row must be an existing one-based row")
    columns = spec.get("columns")
    if not isinstance(columns, dict) or not columns or set(columns) - allowed_fields:
        raise ValueError("columns must map supported canonical fields to exact source headers")
    headers = list(next(sheet.iter_rows(min_row=header_row, max_row=header_row)))
    positions = {}
    for field, header in columns.items():
        matches = [index for index, cell in enumerate(headers) if cell.value == header]
        if len(matches) != 1:
            raise ValueError(f"Header {header!r} must occur exactly once in {sheet.title}")
        positions[field] = matches[0]
    records = []
    for cells in sheet.iter_rows(min_row=header_row + 1):
        if not any(cells[index].value is not None for index in positions.values()):
            continue
        record = {}
        for field, index in positions.items():
            cell = cells[index]
            if cell.data_type in {"f", "e"}:
                raise ValueError(f"{sheet.title}!{cell.coordinate}: formula/error cells require reviewed static facts")
            try:
                record[field] = _convert(field, cell.value, spec.get("value_maps", {}).get(field))
            except ValueError as exc:
                raise ValueError(f"{sheet.title}!{cell.coordinate}: {exc}") from exc
        record["_source"] = {"sheet": sheet.title, "row": cells[0].row}
        records.append(record)
    return records


def import_workbook(path, mapping):
    """Normalize explicitly mapped tables and retain row provenance and gaps.

    Fields omitted from the map remain missing. The matching gate then abstains
    or excludes them. Mapping never inserts fictional data into actual records.
    """
    if mapping.get("units") != {"currency": "CNY", "duration": "calendar_days", "fee": "percent"}:
        raise ValueError("Confirm mapping units: CNY, calendar_days, percent; convert differing source units explicitly first")
    workbook = _open(path)
    try:
        users = _table(workbook, mapping["users"], USER_FIELDS)
        products = _table(workbook, mapping["products"], PRODUCT_FIELDS)
        history = _table(workbook, mapping["history"], HISTORY_FIELDS) if mapping.get("history") else []
    finally:
        workbook.close()
    validate_catalog(products)
    ids = [user.get("user_id") for user in users]
    if any(not isinstance(uid, str) or not uid for uid in ids) or len(set(ids)) != len(ids):
        raise ValueError("Missing or duplicate user_id in mapped table")
    user_issues = [{"user_id": user["user_id"], "issues": profile_errors(user)}
                   for user in users if profile_errors(user)]
    # A complete neutral profile allows product-format checks without filling
    # real user gaps. These diagnostics do not authorize any recommendation.
    neutral = dict(user_id="quality-check", risk_tolerance=5, risk_capacity=5,
                   budget_cny=1e15, horizon_days=10**9, max_redemption_days=10**9,
                   objective="income")
    product_issues = []
    for product in products:
        decision = evaluate_eligibility(neutral, product)
        if decision["reasons"]:
            product_issues.append({"product_id": product["product_id"], "issues": decision["reasons"]})
    for row in history:
        if row.get("user_id") not in ids or row.get("product_id") not in {p["product_id"] for p in products}:
            raise ValueError("History references an unknown user or product")
    return {"provenance": {"source_file": Path(path).name,
                            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                            "mapping": mapping, "synthetic": False},
            "users": users, "products": products, "history": history,
            "quality_report": {"users": user_issues, "products": product_issues,
                               "history": "Ratings and duplicates are validated by the data-driven model"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "import"])
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.workbook.resolve():
        parser.error("Output must not overwrite the source workbook")
    try:
        if args.action == "inspect":
            result = inspect_workbook(args.workbook)
        else:
            if not args.mapping:
                parser.error("import requires --mapping")
            result = import_workbook(args.workbook, json.loads(args.mapping.read_text(encoding="utf-8-sig")))
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        parser.exit(2, f"Import failed: {exc}\n")


if __name__ == "__main__":
    main()
