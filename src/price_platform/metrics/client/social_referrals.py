"""Social referral metrics read/write helpers."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import timedelta

from ..._sqlite_protocols import SQLiteConnectionProvider
from ...platform import clock
from .models import SocialReferralEventRaw, _date_gte


@dataclass(frozen=True)
class SocialReferralSummary:
    """SNS 流入イベントの期間集計。"""

    days: int
    total_events: int
    variants: dict[str, dict[str, int]]
    sources: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        """JSON レスポンス境界用の辞書表現。"""
        return dataclasses.asdict(self)


class ClientMetricsSocialReferralMixin:
    """Persistence helpers for social referral retention events."""

    def save_social_referral_event(self: SQLiteConnectionProvider, data: SocialReferralEventRaw) -> None:
        now = clock.now().replace(tzinfo=None)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO social_referral_events
                (
                    recorded_at, event_name, source, medium, campaign,
                    post_variant, post_id, social_event, session_id,
                    landing_path, page_path, referrer, page_depth,
                    device_type, user_agent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now.isoformat(),
                    data.event_name,
                    data.source,
                    data.medium,
                    data.campaign,
                    data.post_variant,
                    data.post_id,
                    data.social_event,
                    data.session_id,
                    data.landing_path,
                    data.page_path,
                    data.referrer,
                    data.page_depth,
                    data.device_type,
                    data.user_agent,
                ),
            )
            conn.commit()

    def get_social_referral_summary(
        self: SQLiteConnectionProvider, *, days: int = 30
    ) -> SocialReferralSummary:
        since = _date_gte((clock.now().date() - timedelta(days=max(days - 1, 0))).isoformat())
        with self._get_connection() as conn:
            total = conn.execute(
                """
                SELECT COUNT(*) FROM social_referral_events
                WHERE recorded_at >= ?
                """,
                (since,),
            ).fetchone()[0]
            by_variant_rows = conn.execute(
                """
                SELECT COALESCE(post_variant, 'unknown') AS post_variant, event_name, COUNT(*) AS count
                FROM social_referral_events
                WHERE recorded_at >= ?
                GROUP BY COALESCE(post_variant, 'unknown'), event_name
                ORDER BY post_variant, event_name
                """,
                (since,),
            ).fetchall()
            by_source_rows = conn.execute(
                """
                SELECT source, COUNT(*) AS count
                FROM social_referral_events
                WHERE recorded_at >= ?
                GROUP BY source
                ORDER BY count DESC, source
                """,
                (since,),
            ).fetchall()

        variants: dict[str, dict[str, int]] = {}
        for row in by_variant_rows:
            bucket = variants.setdefault(row["post_variant"], {})
            bucket[row["event_name"]] = row["count"]

        return SocialReferralSummary(
            days=days,
            total_events=total,
            variants=variants,
            sources={row["source"]: row["count"] for row in by_source_rows},
        )
