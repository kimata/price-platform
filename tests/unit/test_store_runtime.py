from __future__ import annotations

import price_platform.store_runtime


def test_build_store_runtime_uses_factories() -> None:
    calls: list[str] = []

    runtime = price_platform.store_runtime.build_store_runtime(
        "config",
        price_store_factory=lambda config: calls.append(f"price:{config}") or {"price": config},
        price_event_store_factory=lambda config: calls.append(f"event:{config}") or {"event": config},
    )

    assert runtime.price_store == {"price": "config"}
    assert runtime.price_event_store == {"event": "config"}
    assert calls == ["price:config", "event:config"]
