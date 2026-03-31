"""Shared client-side performance metrics collection and aggregation."""

from __future__ import annotations

import functools
import logging
import pathlib
import sqlite3
import statistics
import threading
from datetime import timedelta

import my_lib.time
from ._client_metrics_sqlite_models import (
    BoxplotData,
    ClientPerfDaily,
    ClientPerfRaw,
    DeviceType,
    MetricName,
    WebVitalBoxplotData,
    WebVitalDaily,
    WebVitalName,
    WebVitalRaw,
    _date_gte,
    _date_lt,
    _date_range,
    _filter_web_vital_values,
    detect_device_type,
)

logger = logging.getLogger(__name__)


class ClientMetricsDB:
    """SQLite database for client performance metrics."""

    def __init__(self, db_path: pathlib.Path, schema_path: pathlib.Path):
        """Initialize the database.

        Args:
            db_path: Path to SQLite database file.
            schema_path: Path to schema file.
        """
        self.db_path = db_path
        self.schema_path = schema_path
        self._lock = threading.Lock()
        self._last_aggregated_date: str | None = None

        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database schema
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                with self.schema_path.open() as f:
                    schema = f.read()
                conn.executescript(schema)
                conn.commit()
            finally:
                conn.close()

    def save_raw(self, data: ClientPerfRaw) -> None:
        """Save raw performance data."""
        now = my_lib.time.now()
        # SQLiteのdate()関数がローカル日付を正しく返すよう、タイムゾーン情報を除去
        now_naive = now.replace(tzinfo=None)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
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
            finally:
                conn.close()

    def aggregate_daily(self, date: str) -> int:
        """Aggregate raw data for a specific date.

        Args:
            date: Date string in YYYY-MM-DD format.

        Returns:
            Number of aggregated entries.
        """
        metrics: list[MetricName] = ["ttfb_ms", "dom_interactive_ms", "dom_complete_ms", "load_event_ms"]
        device_types: list[DeviceType] = ["mobile", "desktop"]

        aggregated_count = 0

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                for device_type in device_types:
                    for metric_name in metrics:
                        # Fetch raw values for the date and device type
                        date_start, date_end = _date_range(date)
                        cursor = conn.execute(
                            f"""
                            SELECT {metric_name}
                            FROM client_perf_raw
                            WHERE recorded_at >= ? AND recorded_at < ?
                              AND device_type = ?
                              AND {metric_name} IS NOT NULL
                            """,  # noqa: S608 (metric_name is from fixed list)
                            (date_start, date_end, device_type),
                        )
                        values = [row[0] for row in cursor.fetchall()]

                        if not values:
                            continue

                        # Calculate statistics
                        sorted_values = sorted(values)
                        n = len(sorted_values)

                        min_val = sorted_values[0]
                        max_val = sorted_values[-1]
                        median_val = statistics.median(sorted_values)
                        avg_val = statistics.mean(values)

                        # Calculate quartiles
                        q1_idx = n // 4
                        q3_idx = (3 * n) // 4
                        q1_val = sorted_values[q1_idx] if q1_idx < n else min_val
                        q3_val = sorted_values[q3_idx] if q3_idx < n else max_val

                        # Upsert daily aggregation
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
            finally:
                conn.close()

        return aggregated_count

    def cleanup_old_raw_data(self, retention_days: int) -> int:
        """Delete raw data older than retention period.

        Args:
            retention_days: Number of days to retain raw data.

        Returns:
            Number of deleted rows.
        """
        cutoff = my_lib.time.now() - timedelta(days=retention_days)
        cutoff_str = cutoff.date().isoformat()

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
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
            finally:
                conn.close()

    def get_daily_boxplot_data(
        self,
        metric_name: MetricName,
        days: int = 30,
    ) -> list[BoxplotData]:
        """Get boxplot data for a metric over the specified period.

        For today and yesterday, if data is not in client_perf_daily,
        it will be computed from client_perf_raw in realtime.

        Args:
            metric_name: The metric to retrieve.
            days: Number of days to include.

        Returns:
            List of BoxplotData sorted by date.
        """
        cutoff = my_lib.time.now() - timedelta(days=days)
        cutoff_str = cutoff.date().isoformat()

        # Get dates that need realtime computation (today and yesterday)
        today = my_lib.time.now().date()
        yesterday = (my_lib.time.now() - timedelta(days=1)).date()
        realtime_dates = [today.isoformat(), yesterday.isoformat()]

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                # Get aggregated data from client_perf_daily
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

                # Check which realtime dates are missing from aggregated data
                aggregated_date_device_pairs = {(d.date, d.device_type) for d in result}
                device_types: list[DeviceType] = ["mobile", "desktop"]

                missing_dates: list[str] = []
                for date_str in realtime_dates:
                    for device_type in device_types:
                        if (date_str, device_type) not in aggregated_date_device_pairs:
                            if date_str not in missing_dates:
                                missing_dates.append(date_str)
                            break

                # Compute missing data from raw table
                for date_str in missing_dates:
                    for device_type in device_types:
                        if (date_str, device_type) not in aggregated_date_device_pairs:
                            stats = self._compute_stats_for_date(conn, date_str, metric_name, device_type)
                            if stats:
                                result.append(stats)
            finally:
                conn.close()

        # Sort by date and device_type
        result.sort(key=lambda x: (x.date, x.device_type))
        return result

    def _compute_stats_for_date(
        self,
        conn: sqlite3.Connection,
        date_str: str,
        metric_name: MetricName,
        device_type: DeviceType,
    ) -> BoxplotData | None:
        """Compute boxplot stats for a specific date from raw data."""
        ds, de = _date_range(date_str)
        cursor = conn.execute(
            f"""
            SELECT {metric_name}
            FROM client_perf_raw
            WHERE recorded_at >= ? AND recorded_at < ?
              AND device_type = ?
              AND {metric_name} IS NOT NULL
            """,  # noqa: S608 (metric_name is from fixed list)
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
        self,
        metric_name: MetricName,
        dates: list[str],
    ) -> list[BoxplotData]:
        """Get realtime stats for specified dates (from raw data).

        Args:
            metric_name: The metric to retrieve.
            dates: List of date strings in YYYY-MM-DD format.

        Returns:
            List of BoxplotData for dates that have data.
        """
        device_types: list[DeviceType] = ["mobile", "desktop"]
        result: list[BoxplotData] = []

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                for date_str in dates:
                    for device_type in device_types:
                        stats = self._compute_stats_for_date(conn, date_str, metric_name, device_type)
                        if stats:
                            result.append(stats)
            finally:
                conn.close()

        return result

    def get_today_realtime_stats(
        self,
        metric_name: MetricName,
    ) -> dict[DeviceType, BoxplotData | None]:
        """Get realtime stats for today (from raw data).

        Args:
            metric_name: The metric to retrieve.

        Returns:
            Dict mapping device_type to BoxplotData (or None if no data).
        """
        today = my_lib.time.now().date().isoformat()
        device_types: list[DeviceType] = ["mobile", "desktop"]
        result: dict[DeviceType, BoxplotData | None] = {}

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                for device_type in device_types:
                    result[device_type] = self._compute_stats_for_date(conn, today, metric_name, device_type)
            finally:
                conn.close()

        return result

    def check_and_aggregate(self) -> bool:
        """Check if daily aggregation is needed and perform it.

        Should be called at crawler startup to aggregate previous day's data.

        Returns:
            True if aggregation was performed.
        """
        today = my_lib.time.now().date().isoformat()

        # Skip if already aggregated today
        if self._last_aggregated_date == today:
            return False

        # Aggregate yesterday's data
        yesterday = (my_lib.time.now() - timedelta(days=1)).date().isoformat()
        count = self.aggregate_daily(yesterday)
        vitals_count = self.aggregate_web_vitals_daily(yesterday)

        if count > 0:
            logger.info(f"クライアントメトリクス: {yesterday} の日次集計を実行 ({count} エントリ)")
        if vitals_count > 0:
            logger.info(f"Core Web Vitals: {yesterday} の日次集計を実行 ({vitals_count} エントリ)")

        self._last_aggregated_date = today
        return count > 0 or vitals_count > 0

    # -------------------------------------------------------------------------
    # Core Web Vitals methods
    # -------------------------------------------------------------------------

    def save_web_vital(self, data: WebVitalRaw) -> None:
        """Save Core Web Vital data."""
        now = my_lib.time.now()
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
        """Aggregate web vitals raw data for a specific date.

        Args:
            date: Date string in YYYY-MM-DD format.

        Returns:
            Number of aggregated entries.
        """
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
        """Get daily web vitals data for boxplot display.

        Args:
            metric_name: The metric to retrieve (LCP, CLS, INP, FCP, TTFB).
            days: Number of days to include.

        Returns:
            List of WebVitalBoxplotData sorted by date.
        """
        cutoff = my_lib.time.now() - timedelta(days=days)
        cutoff_str = cutoff.date().isoformat()

        # Get dates that need realtime computation (today and yesterday)
        today = my_lib.time.now().date()
        yesterday = (my_lib.time.now() - timedelta(days=1)).date()
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

                # Check which realtime dates are missing from aggregated data
                aggregated_date_device_pairs = {(d.date, d.device_type) for d in result}
                device_types: list[DeviceType] = ["mobile", "desktop"]

                for date_str in realtime_dates:
                    for device_type in device_types:
                        if (date_str, device_type) not in aggregated_date_device_pairs:
                            stats = self._compute_web_vital_stats_for_date(
                                conn, date_str, metric_name, device_type
                            )
                            if stats:
                                result.append(stats)
            finally:
                conn.close()

        # Sort by date and device_type
        result.sort(key=lambda x: (x.date, x.device_type))
        return result

    def _compute_web_vital_stats_for_date(
        self,
        conn: sqlite3.Connection,
        date_str: str,
        metric_name: WebVitalName,
        device_type: DeviceType,
    ) -> WebVitalBoxplotData | None:
        """Compute web vitals stats for a specific date from raw data."""
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

        good_pct = (good_count / n * 100) if n > 0 else 0
        ni_pct = (needs_improvement_count / n * 100) if n > 0 else 0
        poor_pct = (poor_count / n * 100) if n > 0 else 0

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
            good_pct=good_pct,
            needs_improvement_pct=ni_pct,
            poor_pct=poor_pct,
        )

    def get_web_vitals_summary(self, days: int = 7) -> dict[str, dict[DeviceType, dict]]:
        """Get summary of all web vitals for the specified period.

        Returns a dict mapping metric_name to device_type to summary stats.
        """
        metric_names: list[WebVitalName] = ["LCP", "CLS", "INP", "FCP", "TTFB"]
        device_types: list[DeviceType] = ["mobile", "desktop"]
        cutoff = my_lib.time.now() - timedelta(days=days)
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

                        # 最新サンプル日時を取得
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
        """Delete web vitals raw data older than retention period."""
        cutoff = my_lib.time.now() - timedelta(days=retention_days)
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


@functools.cache
def generate_boxplot_svg(
    data: tuple[BoxplotData, ...],
    title: str,
    width: int = 800,
    height: int = 400,
) -> str:
    """Generate SVG boxplot from data.

    Args:
        data: Tuple of BoxplotData (must be hashable for caching).
        title: Chart title.
        width: SVG width.
        height: SVG height.

    Returns:
        SVG string.
    """
    if not data:
        return _generate_empty_svg(title, width, height)

    # Group by date
    dates = sorted({d.date for d in data})
    if len(dates) > 30:
        dates = dates[-30:]  # Show last 30 days

    # Layout constants
    margin_left = 60
    margin_right = 20
    margin_top = 50
    margin_bottom = 60
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom

    # Calculate scale
    all_values = [d.max_val for d in data] + [d.min_val for d in data]
    y_min = 0
    y_max = min(max(all_values) * 1.1, 2000) if all_values else 1000

    def y_scale(val: float) -> float:
        return margin_top + chart_height - (val - y_min) / (y_max - y_min) * chart_height

    box_width = min(20, chart_width / len(dates) / 3)
    group_width = chart_width / len(dates)

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        "<style>",
        ".box-mobile { fill: #4ade80; stroke: #16a34a; stroke-width: 1; }",
        ".box-desktop { fill: #60a5fa; stroke: #2563eb; stroke-width: 1; }",
        ".whisker { stroke: #374151; stroke-width: 1; }",
        ".median { stroke: #111827; stroke-width: 2; }",
        ".axis { stroke: #9ca3af; stroke-width: 1; }",
        ".label { font-family: sans-serif; font-size: 10px; fill: #374151; }",
        ".title { font-family: sans-serif; font-size: 14px; fill: #111827; font-weight: bold; }",
        ".legend { font-family: sans-serif; font-size: 11px; fill: #374151; }",
        "</style>",
        # Title
        f'<text x="{width / 2}" y="25" class="title" text-anchor="middle">{title}</text>',
        # Legend
        f'<rect x="{width - 150}" y="10" width="12" height="12" class="box-mobile" />',
        f'<text x="{width - 135}" y="20" class="legend">Mobile</text>',
        f'<rect x="{width - 80}" y="10" width="12" height="12" class="box-desktop" />',
        f'<text x="{width - 65}" y="20" class="legend">Desktop</text>',
    ]

    # Y axis
    y_axis_y2 = margin_top + chart_height
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{y_axis_y2}" class="axis" />'
    )
    # X axis
    x_axis_x2 = margin_left + chart_width
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{y_axis_y2}" x2="{x_axis_x2}" y2="{y_axis_y2}" class="axis" />'
    )

    # Y axis labels
    step = 500 if y_max > 2000 else 200 if y_max > 1000 else 100
    y_val = 0
    while y_val <= y_max:
        y_pos = y_scale(y_val)
        svg_parts.append(
            f'<text x="{margin_left - 5}" y="{y_pos + 4}" class="label" text-anchor="end">{int(y_val)}</text>'
        )
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{y_pos}" x2="{x_axis_x2}" y2="{y_pos}" '
            'stroke="#e5e7eb" stroke-width="1" />'
        )
        y_val += step

    # Draw boxplots
    for i, date_str in enumerate(dates):
        x_center = margin_left + (i + 0.5) * group_width
        date_data = [d for d in data if d.date == date_str]

        # X axis label
        day = int(date_str.split("-")[2])
        label = f"{int(date_str.split('-')[1])}/{day}" if day == 1 or i == 0 else str(day)
        label_y = y_axis_y2 + 15
        svg_parts.append(
            f'<text x="{x_center}" y="{label_y}" class="label" text-anchor="middle">{label}</text>'
        )

        for d in date_data:
            x_offset = -box_width * 0.6 if d.device_type == "mobile" else box_width * 0.6
            x = x_center + x_offset

            box_class = "box-mobile" if d.device_type == "mobile" else "box-desktop"

            y_min_pt = y_scale(d.min_val)
            y_max_pt = y_scale(d.max_val)
            y_median = y_scale(d.median)
            cap_x1 = x - box_width / 4
            cap_x2 = x + box_width / 4
            box_x = x - box_width / 2

            # Whisker (min to max)
            svg_parts.append(f'<line x1="{x}" y1="{y_min_pt}" x2="{x}" y2="{y_max_pt}" class="whisker" />')
            # Min cap
            svg_parts.append(
                f'<line x1="{cap_x1}" y1="{y_min_pt}" x2="{cap_x2}" y2="{y_min_pt}" class="whisker" />'
            )
            # Max cap
            svg_parts.append(
                f'<line x1="{cap_x1}" y1="{y_max_pt}" x2="{cap_x2}" y2="{y_max_pt}" class="whisker" />'
            )
            # Box (Q1 to Q3)
            box_top = y_scale(d.q3)
            box_bottom = y_scale(d.q1)
            box_height = box_bottom - box_top
            svg_parts.append(
                f'<rect x="{box_x}" y="{box_top}" width="{box_width}" '
                f'height="{box_height}" class="{box_class}" />'
            )
            # Median line
            svg_parts.append(
                f'<line x1="{box_x}" y1="{y_median}" '
                f'x2="{x + box_width / 2}" y2="{y_median}" class="median" />'
            )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _generate_empty_svg(title: str, width: int, height: int) -> str:
    """Generate empty SVG when no data is available."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
    <style>
        .title {{ font-family: sans-serif; font-size: 14px; fill: #111827; font-weight: bold; }}
        .message {{ font-family: sans-serif; font-size: 12px; fill: #6b7280; }}
    </style>
    <text x="{width / 2}" y="25" class="title" text-anchor="middle">{title}</text>
    <text x="{width / 2}" y="{height / 2}" class="message" text-anchor="middle">データがありません</text>
</svg>"""
