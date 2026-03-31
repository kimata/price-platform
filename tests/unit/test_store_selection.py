from __future__ import annotations

import pytest

from price_platform.store.selection import (
    append_selection_filter,
    build_current_prices_filter,
    resolve_selection_value,
)


def test_resolve_selection_value_accepts_shared_or_legacy() -> None:
    assert resolve_selection_value(selection_key="black", legacy_value=None, legacy_name="color_id") == "black"
    assert resolve_selection_value(selection_key=None, legacy_value="black", legacy_name="color_id") == "black"


def test_resolve_selection_value_rejects_mismatch() -> None:
    with pytest.raises(ValueError, match="selection_key and color_id mismatch"):
        resolve_selection_value(selection_key="black", legacy_value="white", legacy_name="color_id")


def test_build_current_prices_filter_supports_unknown_guard() -> None:
    clause, params = build_current_prices_filter(
        column_name="color_id",
        product_id="p1",
        selection_value="black",
        include_unassigned=True,
        exclude_used_null_rows=True,
    )

    assert clause == "WHERE product_id = ? AND (color_id = ? OR (color_id IS NULL AND is_used = 0))"
    assert params == ["p1", "black"]


def test_append_selection_filter_appends_predicate() -> None:
    query, params = append_selection_filter(
        query="SELECT * FROM prices WHERE product_id = ?",
        params=["p1"],
        column_name="variant_id",
        selection_value="v1",
    )

    assert query.endswith("AND variant_id = ?")
    assert params == ["p1", "v1"]
