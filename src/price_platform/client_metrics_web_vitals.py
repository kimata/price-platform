"""Core Web Vitals helpers for client metrics."""

from __future__ import annotations

import logging
import sqlite3
import statistics
from datetime import timedelta

from ._client_metrics_sqlite_models import (
    DeviceType,
    WebVitalBoxplotData,
    WebVitalName,
    WebVitalRaw,
    _date_gte,
    _date_lt,
    _date_range,
    _filter_web_vital_values,
)
from .platform import clock

logger = logging.getLogger(__name__)


class ClientMetricsWebVitalsMixin:
    def save_web_vital(self, data: WebVitalRaw) -> None:
        now = clock.now()
        now_naive = now.replace(tzinfo=None)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO web_vitals_raw
                    (recorded_at, device_type, metric_name, metric_value, rating, page_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_naive.isoformat(),
                        data.device_type,
                        data.metric_name,
                        data.metric_value,
                        data.rating,
                        data.page_path,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def aggregate_web_vitals_daily(self, date: str) -> int:
        metric_names: list[WebVitalName] = ["LCP", "CLS", "INP", "FCP", "TTFB"]
        device_types: list[DeviceType] = ["mobile", "desktop"]
        aggregated_count = 0

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                date_start, date_end = _date_range(date)
                for device_type in device_types:
                    for metric_name in metric_names:
                        cursor = conn.execute(
                            """
                            SELECT metric_value, rating
                            FROM web_vitals_raw
                            WHERE recorded_at >= ? AND recorded_at < ?
                              AND device_type = ?
                              AND metric_name = ?
                            """,
                            (date_start, date_end, device_type, metric_name),
                        )
                        rows = cursor.fetchall()
                        if not rows:
                            continue

                        values, ratings = _filter_web_vital_values(metric_name, rows)
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
                        good_count = sum(1 for r in ratings if r == "good")
                        needs_improvement_count = sum(1 for r in ratings if r == "needs-improvement")
                        poor_count = sum(1 for r in ratings if r == "poor")

                        conn.execute(
                            """
                            INSERT INTO web_vitals_daily
                            (date, device_type, metric_name, min_value, q1_value,
                             median_value, q3_value, max_value, avg_value, entry_count,
                             good_count, needs_improvement_count, poor_count)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(date, device_type, metric_name)
                            DO UPDATE SET
                                min_value = excluded.min_value,
                                q1_value = excluded.q1_value,
                                median_value = excluded.median_value,
                                q3_value = excluded.q3_value,
                                max_value = excluded.max_value,
                                avg_value = excluded.avg_value,
                                entry_count = excluded.entry_count,
                                good_count = excluded.good_count,
                                needs_improvement_count = excluded.needs_improvement_count,
                                poor_count = excluded.poor_count
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
                                good_count,
                                needs_improvement_count,
                                poor_count,
                            ),
                        )
                        aggregated_count += 1
                conn.commit()
            finally:
                conn.close()

        return aggregated_count

    def get_web_vitals_daily(
        self,
        metric_name: WebVitalName,
        days: int = 30,
    ) -> list[WebVitalBoxplotData]:
        cutoff = clock.now() - timedelta(days=days)
        cutoff_str = cutoff.date().isoformat()
        today = clock.now().date()
        yesterday = (clock.now() - timedelta(days=1)).date()
        realtime_dates = [today.isoformat(), yesterday.isoformat()]

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    """
                    SELECT date, device_type, min_value, q1_value,
                           median_value, q3_value, max_value, avg_value, entry_count,
                           good_count, needs_improvement_count, poor_count
                    FROM web_vitals_daily
                    WHERE metric_name = ?
                      AND date >= ?
                    ORDER BY date ASC, device_type ASC
                    """,
                    (metric_name, cutoff_str),
                )
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    entry_count = row[8]
                    good_pct = (row[9] / entry_count * 100) if entry_count > 0 else 0
                    ni_pct = (row[10] / entry_count * 100) if entry_count > 0 else 0
                    poor_pct = (row[11] / entry_count * 100) if entry_count > 0 else 0
                    result.append(
                        WebVitalBoxplotData(
                            date=row[0],
                            device_type=row[1],
                            metric_name=metric_name,
                            min_val=row[2],
                            q1=row[3],
                            median=row[4],
                            q3=row[5],
                            max_val=row[6],
                            avg=row[7],
                            count=entry_count,
                            good_pct=good_pct,
                            needs_improvement_pct=ni_pct,
                            poor_pct=poor_pct,
                        )
                    )

                aggregated_date_device_pairs = {(d.date, d.device_type) for d in result}
                device_types: list[DeviceType] = ["mobile", "desktop"]
                for date_str in realtime_dates:
                    for device_type in device_types:
                        if (date_str, device_type) not in aggregated_date_device_pairs:
                            stats = self._compute_web_vital_stats_for_date(conn, date_str, metric_name, device_type)
                            if stats:
                                result.append(stats)
            finally:
                conn.close()

        result.sort(key=lambda x: (x.date, x.device_type))
        return result

    def _compute_web_vital_stats_for_date(
        self,
        conn: sqlite3.Connection,
        date_str: str,
        metric_name: WebVitalName,
        device_type: DeviceType,
    ) -> WebVitalBoxplotData | None:
        ds, de = _date_range(date_str)
        cursor = conn.execute(
            """
            SELECT metric_value, rating
            FROM web_vitals_raw
            WHERE recorded_at >= ? AND recorded_at < ?
              AND device_type = ?
              AND metric_name = ?
            """,
            (ds, de, device_type, metric_name),
        )
        rows = cursor.fetchall()
        if not rows:
            return None

        values, ratings = _filter_web_vital_values(metric_name, rows)
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
        good_count = sum(1 for r in ratings if r == "good")
        needs_improvement_count = sum(1 for r in ratings if r == "needs-improvement")
        poor_count = sum(1 for r in ratings if r == "poor")

        return WebVitalBoxplotData(
            date=date_str,
            device_type=device_type,
            metric_name=metric_name,
            min_val=min_val,
            q1=q1_val,
            median=median_val,
            q3=q3_val,
            max_val=max_val,
            avg=avg_val,
            count=n,
            good_pct=(good_count / n * 100) if n > 0 else 0,
            needs_improvement_pct=(needs_improvement_count / n * 100) if n > 0 else 0,
            poor_pct=(poor_count / n * 100) if n > 0 else 0,
        )

    def get_web_vitals_summary(self, days: int = 7) -> dict[str, dict[DeviceType, dict]]:
        metric_names: list[WebVitalName] = ["LCP", "CLS", "INP", "FCP", "TTFB"]
        device_types: list[DeviceType] = ["mobile", "desktop"]
        cutoff = clock.now() - timedelta(days=days)
        cutoff_str = cutoff.date().isoformat()
        result: dict[str, dict[DeviceType, dict]] = {}

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                for metric_name in metric_names:
                    result[metric_name] = {}
                    for device_type in device_types:
                        cutoff_ts = _date_gte(cutoff_str)
                        cursor = conn.execute(
                            """
                            SELECT metric_value, rating
                            FROM web_vitals_raw
                            WHERE recorded_at >= ?
                              AND device_type = ?
                              AND metric_name = ?
                            """,
                            (cutoff_ts, device_type, metric_name),
                        )
                        rows = cursor.fetchall()
                        values, ratings = _filter_web_vital_values(metric_name, rows) if rows else ([], [])
                        if not values:
                            result[metric_name][device_type] = {
                                "count": 0,
                                "median": None,
                                "p75": None,
                                "good_pct": 0,
                                "needs_improvement_pct": 0,
                                "poor_pct": 0,
                                "latest_sample_at": None,
                            }
                            continue

                        latest_cursor = conn.execute(
                            """
                            SELECT MAX(recorded_at)
                            FROM web_vitals_raw
                            WHERE recorded_at >= ?
                              AND device_type = ?
                              AND metric_name = ?
                            """,
                            (cutoff_ts, device_type, metric_name),
                        )
                        latest_row = latest_cursor.fetchone()
                        latest_sample_at = latest_row[0] if latest_row else None

                        sorted_values = sorted(values)
                        n = len(sorted_values)
                        median_val = statistics.median(sorted_values)
                        p75_idx = int(n * 0.75)
                        p75_val = sorted_values[p75_idx] if p75_idx < n else sorted_values[-1]
                        good_count = sum(1 for r in ratings if r == "good")
                        ni_count = sum(1 for r in ratings if r == "needs-improvement")
                        poor_count = sum(1 for r in ratings if r == "poor")

                        result[metric_name][device_type] = {
                            "count": n,
                            "median": round(median_val, 2),
                            "p75": round(p75_val, 2),
                            "good_pct": round(good_count / n * 100, 1),
                            "needs_improvement_pct": round(ni_count / n * 100, 1),
                            "poor_pct": round(poor_count / n * 100, 1),
                            "latest_sample_at": latest_sample_at,
                        }
            finally:
                conn.close()

        return result

    def cleanup_old_web_vitals(self, retention_days: int) -> int:
        cutoff = clock.now() - timedelta(days=retention_days)
        cutoff_str = cutoff.date().isoformat()

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    """
                    DELETE FROM web_vitals_raw
                    WHERE recorded_at < ?
                    """,
                    (_date_lt(cutoff_str),),
                )
                deleted = cursor.rowcount
                conn.commit()
                return deleted
            finally:
                conn.close()
