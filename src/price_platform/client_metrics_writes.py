"""Write-side helpers for client metrics persistence."""

from __future__ import annotations

import logging
import statistics
from datetime import timedelta

from ._client_metrics_sqlite_models import ClientPerfRaw, DeviceType, MetricName, _date_lt, _date_range
from ._sqlite_protocols import ClientMetricsAggregateProvider, SQLiteConnectionProvider
from .platform import clock

logger = logging.getLogger(__name__)


class ClientMetricsWriteMixin:
    def save_raw(self: SQLiteConnectionProvider, data: ClientPerfRaw) -> None:
        now = clock.now()
        now_naive = now.replace(tzinfo=None)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO client_perf_raw
                (recorded_at, device_type, ttfb_ms, dom_interactive_ms,
                 dom_complete_ms, load_event_ms, page_path, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_naive.isoformat(),
                    data.device_type,
                    data.ttfb_ms,
                    data.dom_interactive_ms,
                    data.dom_complete_ms,
                    data.load_event_ms,
                    data.page_path,
                    data.user_agent,
                ),
            )
            conn.commit()

    def aggregate_daily(self: SQLiteConnectionProvider, date: str) -> int:
        metrics: list[MetricName] = ["ttfb_ms", "dom_interactive_ms", "dom_complete_ms", "load_event_ms"]
        device_types: list[DeviceType] = ["mobile", "desktop"]
        aggregated_count = 0

        with self._get_connection() as conn:
            for device_type in device_types:
                for metric_name in metrics:
                    date_start, date_end = _date_range(date)
                    cursor = conn.execute(
                        f"""
                        SELECT {metric_name}
                        FROM client_perf_raw
                        WHERE recorded_at >= ? AND recorded_at < ?
                          AND device_type = ?
                          AND {metric_name} IS NOT NULL
                        """,  # noqa: S608
                        (date_start, date_end, device_type),
                    )
                    values = [row[0] for row in cursor.fetchall()]
                    if not values:
                        continue

                    sorted_values = sorted(values)
                    n = len(sorted_values)
                    min_val = sorted_values[0]
                    max_val = sorted_values[-1]
                    median_val = statistics.median(sorted_values)
                    avg_val = statistics.mean(values)
                    q1_idx = n // 4
                    q3_idx = (3 * n) // 4
                    q1_val = sorted_values[q1_idx] if q1_idx < n else min_val
                    q3_val = sorted_values[q3_idx] if q3_idx < n else max_val

                    conn.execute(
                        """
                        INSERT INTO client_perf_daily
                        (date, device_type, metric_name, min_value, q1_value,
                         median_value, q3_value, max_value, avg_value, entry_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(date, device_type, metric_name)
                        DO UPDATE SET
                            min_value = excluded.min_value,
                            q1_value = excluded.q1_value,
                            median_value = excluded.median_value,
                            q3_value = excluded.q3_value,
                            max_value = excluded.max_value,
                            avg_value = excluded.avg_value,
                            entry_count = excluded.entry_count
                        """,
                        (
                            date,
                            device_type,
                            metric_name,
                            min_val,
                            q1_val,
                            median_val,
                            q3_val,
                            max_val,
                            avg_val,
                            n,
                        ),
                    )
                    aggregated_count += 1
            conn.commit()

        return aggregated_count

    def cleanup_old_raw_data(self: SQLiteConnectionProvider, retention_days: int) -> int:
        cutoff = clock.now() - timedelta(days=retention_days)
        cutoff_str = cutoff.date().isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM client_perf_raw
                WHERE recorded_at < ?
                """,
                (_date_lt(cutoff_str),),
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def check_and_aggregate(self: ClientMetricsAggregateProvider) -> bool:
        today = clock.now().date().isoformat()
        if self._last_aggregated_date == today:
            return False

        yesterday = (clock.now() - timedelta(days=1)).date().isoformat()
        count = self.aggregate_daily(yesterday)
        vitals_count = self.aggregate_web_vitals_daily(yesterday)

        if count > 0:
            logger.info("クライアントメトリクス: %s の日次集計を実行 (%d エントリ)", yesterday, count)
        if vitals_count > 0:
            logger.info("Core Web Vitals: %s の日次集計を実行 (%d エントリ)", yesterday, vitals_count)

        self._last_aggregated_date = today
        return count > 0 or vitals_count > 0
