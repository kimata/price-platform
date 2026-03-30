"""Twitter posting worker for price-platform applications."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import my_lib.time

from ..config.models import TwitterConfig
from .notification_store import NotificationItem, NotificationStore

# Interval to suppress duplicate postings for the same product (24 hours)
DUPLICATE_PRODUCT_INTERVAL_SEC = 24 * 60 * 60

if TYPE_CHECKING:
    import tweepy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TwitterRateLimit:
    """Twitter API 24-hour rate limit information."""

    app_limit: int  # x-app-limit-24hour-limit
    app_remaining: int  # x-app-limit-24hour-remaining
    app_reset: datetime  # x-app-limit-24hour-reset (converted)
    user_limit: int  # x-user-limit-24hour-limit
    user_remaining: int  # x-user-limit-24hour-remaining
    user_reset: datetime  # x-user-limit-24hour-reset (converted)

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> TwitterRateLimit | None:
        """Extract rate limit info from HTTP response headers."""
        try:
            tz = my_lib.time.get_zoneinfo()
            return cls(
                app_limit=int(headers.get("x-app-limit-24hour-limit", "0")),
                app_remaining=int(headers.get("x-app-limit-24hour-remaining", "0")),
                app_reset=datetime.fromtimestamp(
                    int(headers.get("x-app-limit-24hour-reset", "0")),
                    tz=tz,
                ),
                user_limit=int(headers.get("x-user-limit-24hour-limit", "0")),
                user_remaining=int(headers.get("x-user-limit-24hour-remaining", "0")),
                user_reset=datetime.fromtimestamp(
                    int(headers.get("x-user-limit-24hour-reset", "0")),
                    tz=tz,
                ),
            )
        except (ValueError, OSError):
            return None

    @property
    def is_limited(self) -> bool:
        """Whether the rate limit has been reached."""
        return self.app_remaining <= 0 or self.user_remaining <= 0

    @property
    def next_reset(self) -> datetime:
        """Next time posting becomes available (later of the two resets)."""
        return max(self.app_reset, self.user_reset)

    @property
    def wait_seconds(self) -> int:
        """Seconds to wait until the rate limit resets."""
        delta = self.next_reset - my_lib.time.now()
        return max(0, int(delta.total_seconds())) + 60  # +60s margin


class TwitterPoster:
    """Background worker for posting notifications to Twitter.

    This worker runs in a dedicated thread and processes notifications
    from the queue with a configurable interval between posts.
    """

    def __init__(self, config: TwitterConfig, store: NotificationStore):
        """Initialize Twitter poster.

        Args:
            config: Twitter API configuration
            store: Notification store for queue persistence
        """
        self._config = config
        self._store = store
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._new_item_event = threading.Event()
        self._client: tweepy.Client | None = None

    def start(self) -> None:
        """Start the background posting worker."""
        if not self._config.enabled:
            logger.info("Twitter notification is disabled")
            return

        if self._worker_thread is not None and self._worker_thread.is_alive():
            logger.warning("Twitter poster worker is already running")
            return

        self._stop_event.clear()
        self._client = self._create_client()
        self._worker_thread = threading.Thread(
            target=self._worker,
            name="twitter-poster",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Twitter poster worker started")

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the background posting worker.

        Args:
            timeout: Maximum time to wait for worker to stop
        """
        self._stop_event.set()
        self._new_item_event.set()  # Wake up the worker if waiting
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logger.warning("Twitter poster worker did not stop within timeout")
            else:
                logger.info("Twitter poster worker stopped")
        self._worker_thread = None
        self._client = None

    def notify_new_item(self) -> None:
        """Notify the worker that a new item has been added to the queue.

        This can be called after enqueueing a new notification to wake up
        the worker if it's waiting for items.
        """
        self._new_item_event.set()

    @property
    def is_running(self) -> bool:
        """Check if the worker is running."""
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def _create_client(self) -> tweepy.Client:
        """Create Twitter API client."""
        import tweepy

        return tweepy.Client(
            consumer_key=self._config.api_key,
            consumer_secret=self._config.api_secret,
            access_token=self._config.access_token,
            access_token_secret=self._config.access_token_secret,
        )

    def _worker(self) -> None:
        """Background worker loop."""
        logger.debug("Twitter poster worker loop started")

        # Check for persisted rate limit state from previous run
        self._wait_for_rate_limit_reset()

        while not self._stop_event.is_set():
            try:
                self._process_queue()
            except Exception:
                logger.exception("Error in Twitter poster worker")
                # Wait a bit before retrying on unexpected errors
                if self._stop_event.wait(60):
                    break

    def _wait_for_rate_limit_reset(self) -> None:
        """Check persisted rate limit state and wait if still limited."""
        state = self._store.get_rate_limit_state()
        if state is None:
            return

        now = my_lib.time.now()
        if state.next_available_at <= now:
            logger.info("保存されたレート制限は解除済み、状態をクリアします")
            self._store.clear_rate_limit_state()
            return

        wait_seconds = int((state.next_available_at - now).total_seconds()) + 60
        logger.info(
            "前回のレート制限がまだ有効: %s まで待機 (あと %d 分)",
            state.next_available_at.strftime("%m/%d %H:%M"),
            wait_seconds // 60,
        )
        if self._stop_event.wait(wait_seconds):
            return

        self._store.clear_rate_limit_state()

    def _process_queue(self) -> None:
        """Process pending notifications from the queue."""
        last_posted = self._store.get_last_posted_time()
        if last_posted is not None:
            elapsed = (my_lib.time.now() - last_posted).total_seconds()
            wait_time = self._config.post_interval_sec - elapsed
            if wait_time > 0:
                logger.debug("Waiting %.1f seconds before next post", wait_time)
                if self._stop_event.wait(wait_time):
                    return

        item = self._store.get_next_pending()
        if item is None:
            logger.debug("No pending notifications, waiting for new items")
            self._new_item_event.clear()
            self._new_item_event.wait(timeout=60)
            return

        self._post_item(item)

    def _post_item(self, item: NotificationItem) -> None:
        """Post a single notification to Twitter.

        Args:
            item: The notification item to post
        """
        if self._client is None:
            logger.error("Twitter client not initialized")
            self._store.mark_failed(item.id, "Client not initialized")
            return

        last_posted = self._store.get_last_posted_time_for_product(item.product_id)
        if last_posted is not None:
            elapsed = my_lib.time.now() - last_posted
            if elapsed < timedelta(seconds=DUPLICATE_PRODUCT_INTERVAL_SEC):
                remaining_hours = (
                    timedelta(seconds=DUPLICATE_PRODUCT_INTERVAL_SEC) - elapsed
                ).total_seconds() / 3600
                reason = f"同一製品の投稿から24時間未経過（残り {remaining_hours:.1f} 時間）"
                logger.info("スキップ: %s - %s", item.product_id, reason)
                self._store.mark_skipped(item.id, reason)
                return

        import tweepy

        try:
            response = self._client.create_tweet(text=item.message)
            data = response.data  # type: ignore[attr-defined]  # tweepy type stubs incomplete
            tweet_id = data.get("id") if data else None
            self._store.mark_posted(item.id, tweet_id)
            self._store.clear_rate_limit_state()
            logger.info(
                "Posted tweet for %s: tweet_id=%s",
                item.product_id,
                tweet_id,
            )
        except tweepy.TooManyRequests as e:
            rate_limit = None
            if hasattr(e, "response") and e.response is not None:
                rate_limit = TwitterRateLimit.from_headers(dict(e.response.headers))

            if rate_limit:
                logger.warning(
                    "Twitter投稿制限に到達: %s (アプリ: %d/%d, ユーザー: %d/%d)",
                    item.product_id,
                    rate_limit.app_remaining,
                    rate_limit.app_limit,
                    rate_limit.user_remaining,
                    rate_limit.user_limit,
                )
                logger.info(
                    "リセット時刻 - アプリ: %s, ユーザー: %s (あと %d 分待機)",
                    rate_limit.app_reset.strftime("%m/%d %H:%M"),
                    rate_limit.user_reset.strftime("%m/%d %H:%M"),
                    rate_limit.wait_seconds // 60,
                )

                self._store.save_rate_limit_state(
                    next_available_at=rate_limit.next_reset,
                    app_reset=rate_limit.app_reset,
                    user_reset=rate_limit.user_reset,
                )

                self._stop_event.wait(rate_limit.wait_seconds)
            else:
                logger.warning("Twitter投稿制限（詳細不明）: %s", item.product_id)
                self._stop_event.wait(900)
        except tweepy.TweepyException as e:
            error_msg = str(e)
            logger.warning("Failed to post tweet for %s: %s", item.product_id, error_msg)

            if "429" in error_msg or "rate limit" in error_msg.lower():
                logger.info("レート制限検出（fallback）、15分待機後にリトライします")
                self._stop_event.wait(900)
            else:
                retry_count = self._store.increment_retry_count(item.id, error_msg)
                if retry_count >= 3:
                    logger.warning(
                        "Twitter投稿が3回失敗、諦めます: %s",
                        item.product_id,
                    )
                    self._store.mark_failed(item.id, f"3回リトライ後に失敗: {error_msg}")
                else:
                    logger.info(
                        "Twitter投稿失敗 (%d/3回)、60秒待機後にリトライします: %s",
                        retry_count,
                        item.product_id,
                    )
                    self._stop_event.wait(60)
