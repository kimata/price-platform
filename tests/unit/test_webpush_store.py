"""BaseWebPushStore の購読フィルタと保存のテスト (B3 / B15 回帰)。"""

from __future__ import annotations

import pathlib

import pytest

from price_platform.notification.webpush_store import BaseWebPushStore


@pytest.fixture
def store(tmp_path: pathlib.Path) -> BaseWebPushStore:
    return BaseWebPushStore(db_path=tmp_path / "webpush.db")


def _save(store: BaseWebPushStore, endpoint: str = "https://push.example/ep1", **filters) -> int:
    return store.save_subscription(endpoint, "p256dh", "auth", **filters)


class TestProductFilterMatching:
    """B3 回帰: 商品指定購読が「限定購読」として機能すること."""

    def test_product_only_subscription_excludes_other_products(self, store: BaseWebPushStore) -> None:
        _save(store, product_filter=["product-a"])

        matched = store.get_active_subscriptions_for_event(
            group="lens", event_type="PRICE_DROP", product_id="product-b"
        )

        assert matched == [], "商品指定のみの購読に別商品の通知が届く (B3 再発)"

    def test_product_only_subscription_receives_listed_product(self, store: BaseWebPushStore) -> None:
        _save(store, product_filter=["product-a"])

        matched = store.get_active_subscriptions_for_event(
            group="lens", event_type="PRICE_DROP", product_id="product-a"
        )

        assert len(matched) == 1

    def test_product_and_group_subscription_is_or_condition(self, store: BaseWebPushStore) -> None:
        _save(store, product_filter=["product-a"], group_filter=["lens"])

        # 商品一致 → 受信
        assert store.get_active_subscriptions_for_event(
            group="tool", event_type=None, product_id="product-a"
        )
        # 商品不一致でもグループ一致 → 受信
        assert store.get_active_subscriptions_for_event(
            group="lens", event_type=None, product_id="product-b"
        )
        # どちらも不一致 → 受信しない
        assert not store.get_active_subscriptions_for_event(
            group="tool", event_type=None, product_id="product-b"
        )

    def test_no_filter_subscription_receives_everything(self, store: BaseWebPushStore) -> None:
        _save(store)

        assert store.get_active_subscriptions_for_event(
            group="lens", event_type="PRICE_DROP", product_id="product-x"
        )

    def test_empty_product_filter_is_distinct_from_none(self, store: BaseWebPushStore) -> None:
        """空リスト (何も受信しない) と None (全受信) が保存層で区別されること."""
        _save(store, product_filter=[])

        record = store.get_subscription_by_endpoint("https://push.example/ep1")
        assert record is not None
        assert record.product_filter == []

        assert not store.get_active_subscriptions_for_event(
            group="lens", event_type=None, product_id="product-a"
        )

    def test_unsubscribing_last_product_keeps_empty_list(self, store: BaseWebPushStore) -> None:
        _save(store, product_filter=["product-a"])
        store.update_product_filter("https://push.example/ep1", "product-a", subscribe=False)

        record = store.get_subscription_by_endpoint("https://push.example/ep1")
        assert record is not None
        assert record.product_filter == []


class TestSaveSubscriptionUpsert:
    """B15 回帰: 保存がアトミックな upsert で行われること."""

    def test_save_twice_updates_in_place(self, store: BaseWebPushStore) -> None:
        first_id = _save(store, group_filter=["lens"])
        second_id = store.save_subscription(
            "https://push.example/ep1", "p256dh-2", "auth-2", group_filter=["tool"]
        )

        assert first_id == second_id
        record = store.get_subscription_by_endpoint("https://push.example/ep1")
        assert record is not None
        assert record.p256dh_key == "p256dh-2"
        assert record.group_filter == ["tool"]

    def test_save_reactivates_expired_subscription(self, store: BaseWebPushStore) -> None:
        _save(store)
        store.mark_expired("https://push.example/ep1")

        _save(store)

        record = store.get_subscription_by_endpoint("https://push.example/ep1")
        assert record is not None
        assert record.is_active


class TestConsecutiveFailureTracking:
    """B12 回帰: 連続失敗カウントの記録とリセット."""

    def test_failure_count_increments_and_resets(self, store: BaseWebPushStore) -> None:
        _save(store)

        assert store.record_delivery_failure("https://push.example/ep1") == 1
        assert store.record_delivery_failure("https://push.example/ep1") == 2
        store.record_delivery_success("https://push.example/ep1")
        assert store.record_delivery_failure("https://push.example/ep1") == 1

    def test_failure_count_for_unknown_endpoint_is_zero(self, store: BaseWebPushStore) -> None:
        assert store.record_delivery_failure("https://push.example/unknown") == 0
