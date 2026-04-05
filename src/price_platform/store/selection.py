"""selection 対応ストアクエリの共通ヘルパー。"""

from __future__ import annotations


def build_current_prices_filter(
    *,
    column_name: str,
    product_id: str,
    selection_value: str | None,
    include_unassigned: bool,
    exclude_used_null_rows: bool = False,
) -> tuple[str, list[object]]:
    """Build a WHERE clause and params for current-price lookups."""
    params: list[object] = [product_id]
    if selection_value is None:
        return "WHERE product_id = ?", params

    if include_unassigned:
        if exclude_used_null_rows:
            params.append(selection_value)
            return (
                f"WHERE product_id = ? AND ({column_name} = ? OR ({column_name} IS NULL AND is_used = 0))",
                params,
            )
        params.append(selection_value)
        return f"WHERE product_id = ? AND ({column_name} = ? OR {column_name} IS NULL)", params

    params.append(selection_value)
    return f"WHERE product_id = ? AND {column_name} = ?", params


def append_selection_filter(
    *,
    query: str,
    params: list[object],
    column_name: str,
    selection_value: str | None,
) -> tuple[str, list[object]]:
    """Append an equality filter for a selection column when needed."""
    if selection_value is None:
        return query, params
    return f"{query} AND {column_name} = ?", [*params, selection_value]
