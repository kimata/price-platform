"""クライアントメトリクス向け箱ひげ図・リアルタイム集計ヘルパー。"""

from __future__ import annotations

import sqlite3
import statistics
from datetime import timedelta

from ._client_metrics_sqlite_models import BoxplotData, DeviceType, MetricName, _date_range
from ._sqlite_protocols import ClientMetricsBoxplotProvider
from .platform import clock


class ClientMetricsBoxplotMixin:
    def get_daily_boxplot_data(
        self: ClientMetricsBoxplotProvider,
        metric_name: MetricName,
        days: int = 30,
    ) -> list[BoxplotData]:
        cutoff = clock.now() - timedelta(days=days)
        cutoff_str = cutoff.date().isoformat()
        today = clock.now().date()
        yesterday = (clock.now() - timedelta(days=1)).date()
        realtime_dates = [today.isoformat(), yesterday.isoformat()]

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT date, device_type, min_value, q1_value,
                       median_value, q3_value, max_value, avg_value, entry_count
                FROM client_perf_daily
                WHERE metric_name = ?
                  AND date >= ?
                ORDER BY date ASC, device_type ASC
                """,
                (metric_name, cutoff_str),
            )
            rows = cursor.fetchall()

            result = [
                BoxplotData(
                    date=row[0],
                    device_type=row[1],
                    min_val=row[2],
                    q1=row[3],
                    median=row[4],
                    q3=row[5],
                    max_val=row[6],
                    avg=row[7],
                    count=row[8],
                )
                for row in rows
            ]

            aggregated_date_device_pairs = {(d.date, d.device_type) for d in result}
            device_types: list[DeviceType] = ["mobile", "desktop"]

            missing_dates: list[str] = []
            for date_str in realtime_dates:
                for device_type in device_types:
                    if (date_str, device_type) not in aggregated_date_device_pairs:
                        if date_str not in missing_dates:
                            missing_dates.append(date_str)
                        break

            for date_str in missing_dates:
                for device_type in device_types:
                    if (date_str, device_type) not in aggregated_date_device_pairs:
                        stats = self._compute_stats_for_date(conn, date_str, metric_name, device_type)
                        if stats:
                            result.append(stats)

        result.sort(key=lambda x: (x.date, x.device_type))
        return result

    def _compute_stats_for_date(
        self: ClientMetricsBoxplotProvider,
        conn: sqlite3.Connection,
        date_str: str,
        metric_name: MetricName,
        device_type: DeviceType,
    ) -> BoxplotData | None:
        ds, de = _date_range(date_str)
        cursor = conn.execute(
            f"""
            SELECT {metric_name}
            FROM client_perf_raw
            WHERE recorded_at >= ? AND recorded_at < ?
              AND device_type = ?
              AND {metric_name} IS NOT NULL
            """,  # noqa: S608
            (ds, de, device_type),
        )
        values = [row[0] for row in cursor.fetchall()]
        if not values:
            return None

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

        return BoxplotData(
            date=date_str,
            device_type=device_type,
            min_val=min_val,
            q1=q1_val,
            median=median_val,
            q3=q3_val,
            max_val=max_val,
            avg=avg_val,
            count=n,
        )

    def get_realtime_stats_for_dates(
        self: ClientMetricsBoxplotProvider,
        metric_name: MetricName,
        dates: list[str],
    ) -> list[BoxplotData]:
        device_types: list[DeviceType] = ["mobile", "desktop"]
        result: list[BoxplotData] = []

        with self._get_connection() as conn:
            for date_str in dates:
                for device_type in device_types:
                    stats = self._compute_stats_for_date(conn, date_str, metric_name, device_type)
                    if stats:
                        result.append(stats)

        return result

    def get_today_realtime_stats(
        self: ClientMetricsBoxplotProvider,
        metric_name: MetricName,
    ) -> dict[DeviceType, BoxplotData | None]:
        today = clock.now().date().isoformat()
        device_types: list[DeviceType] = ["mobile", "desktop"]
        result: dict[DeviceType, BoxplotData | None] = {}

        with self._get_connection() as conn:
            for device_type in device_types:
                result[device_type] = self._compute_stats_for_date(conn, today, metric_name, device_type)

        return result
