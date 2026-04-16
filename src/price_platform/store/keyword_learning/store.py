from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from price_platform.platform import clock
from price_platform.schema_registry import resolve_schema_path
from price_platform.sqlite_store import SQLiteStoreBase
from price_platform.store.fetcher_common import FilterResult

from .types import (
    FilterObservationContext,
    KeywordProposal,
    ObservationRecord,
    ProposalKind,
    ProposalStatus,
    serialize_json_payload,
)


class KeywordLearningStore(SQLiteStoreBase):
    def __init__(self, db_path: Path) -> None:
        super().__init__(
            db_path=db_path,
            schema_path=resolve_schema_path("sqlite_keyword_learning.schema"),
        )

    def record_filter_result(
        self,
        *,
        context: FilterObservationContext,
        result: FilterResult[object],
        title_normalizer: Callable[[str], str],
    ) -> None:
        with self.connection() as conn:
            for decision in result.decisions:
                listing = decision.listing
                listing_url = getattr(listing, "url", None) or ""
                if not listing_url:
                    continue
                listing_title = getattr(listing, "title", "") or ""
                conn.execute(
                    """
                    INSERT OR IGNORE INTO listing_observations (
                        project, product_id, product_name, store_name, listing_url, listing_title, listing_price,
                        admitted, reason, missing_keywords_json, matched_ng_words_json,
                        matched_partial_item_words_json, matched_parts_words_json,
                        matched_exclude_product_name, required_keywords_json, anchor_keywords_json,
                        exclude_product_names_json, reference_price, title_normalized, captured_at, observation_day
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        context.project,
                        context.product_id,
                        context.product_name,
                        context.store_name,
                        listing_url,
                        listing_title,
                        int(getattr(listing, "price", 0) or 0),
                        int(decision.admitted),
                        decision.reason.value if decision.reason else None,
                        json.dumps(decision.missing_keywords),
                        json.dumps(decision.matched_ng_words),
                        json.dumps(decision.matched_partial_item_words),
                        json.dumps(decision.matched_parts_words),
                        decision.matched_exclude_product_name,
                        json.dumps(result.rule.required_keywords),
                        json.dumps(result.rule.anchor_keywords),
                        json.dumps(result.rule.exclude_product_names),
                        context.reference_price,
                        title_normalizer(listing_title),
                        context.captured_at.isoformat(),
                        context.captured_at.date().isoformat(),
                    ),
                )
            conn.commit()

    def list_observations(
        self,
        *,
        project: str | None = None,
        product_id: str | None = None,
    ) -> list[ObservationRecord]:
        query = "SELECT * FROM listing_observations WHERE 1 = 1"
        params: list[object] = []
        if project is not None:
            query += " AND project = ?"
            params.append(project)
        if product_id is not None:
            query += " AND product_id = ?"
            params.append(product_id)
        query += " ORDER BY captured_at DESC"

        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_observation(row) for row in rows]

    def upsert_proposal(self, proposal: KeywordProposal) -> int:
        return self.upsert_proposal_for_run(
            proposal,
            run_created_at=proposal.created_at or clock.now(),
        )

    def upsert_proposal_for_run(self, proposal: KeywordProposal, *, run_created_at: datetime) -> int:
        created_at = run_created_at
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO keyword_proposals (
                    project, product_id, product_name, kind, payload_json, metrics_json, evidence_json,
                    analysis_window_start, analysis_window_end, score, status, reviewer, review_note,
                    reviewed_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project, product_id, kind, payload_json, analysis_window_start, analysis_window_end)
                DO UPDATE SET
                    metrics_json = excluded.metrics_json,
                    evidence_json = excluded.evidence_json,
                    score = excluded.score,
                    status = CASE
                        WHEN keyword_proposals.status = 'approved' THEN keyword_proposals.status
                        ELSE excluded.status
                    END
                """,
                (
                    proposal.project,
                    proposal.product_id,
                    proposal.product_name,
                    proposal.kind.value,
                    serialize_json_payload(proposal.payload),
                    json.dumps(proposal.metrics, ensure_ascii=True, sort_keys=True),
                    json.dumps(proposal.evidence, ensure_ascii=True, sort_keys=True),
                    proposal.analysis_window.started_at.isoformat() if proposal.analysis_window.started_at else None,
                    proposal.analysis_window.ended_at.isoformat() if proposal.analysis_window.ended_at else None,
                    proposal.score,
                    proposal.status.value,
                    proposal.reviewer,
                    proposal.review_note,
                    proposal.reviewed_at.isoformat() if proposal.reviewed_at else None,
                    created_at.isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def record_analysis_run(
        self,
        *,
        project: str | None,
        started_at: datetime,
        observation_count: int,
        proposal_count: int,
        candidate_payloads: set[str],
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO keyword_analysis_runs (
                    project, started_at, observation_count, proposal_count, candidate_payloads_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project,
                    started_at.isoformat(),
                    observation_count,
                    proposal_count,
                    json.dumps(sorted(candidate_payloads), ensure_ascii=True),
                ),
            )
            conn.commit()

    def prior_run_payload_counts(
        self,
        *,
        project: str | None,
        before_started_at: datetime,
        max_age_days: int = 14,
    ) -> dict[str, int]:
        cutoff = before_started_at.timestamp() - (max_age_days * 24 * 60 * 60)
        query = """
            SELECT started_at, candidate_payloads_json
            FROM keyword_analysis_runs
            WHERE started_at <= ?
              AND strftime('%s', started_at) >= ?
              AND (? IS NULL OR project = ?)
            ORDER BY started_at DESC
        """
        params: tuple[object, ...] = (
            before_started_at.isoformat(),
            int(cutoff),
            project,
            project,
        )

        with self.connection() as conn:
            run_rows = conn.execute(query, params).fetchall()
        run_payloads = [
            payloads
            for row in run_rows
            if (payloads := set(json.loads(row["candidate_payloads_json"])))
        ]

        active_counts: dict[str, int] = {}
        for run_index, payloads in enumerate(run_payloads):
            if run_index == 0:
                active_counts = dict.fromkeys(payloads, 1)
                continue
            active_counts = {
                payload: active_counts[payload] + 1 for payload in active_counts.keys() & payloads
            }
            if not active_counts:
                break
        return active_counts

    def prune_observations(self, *, older_than_days: int, project: str | None = None) -> int:
        cutoff = (clock.now().date() - timedelta(days=older_than_days)).isoformat()
        query = "DELETE FROM listing_observations WHERE observation_day < ?"
        params: list[object] = [cutoff]
        if project is not None:
            query += " AND project = ?"
            params.append(project)
        with self.connection() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
        return cursor.rowcount

    def list_proposals(
        self,
        *,
        project: str | None = None,
        status: ProposalStatus | None = None,
    ) -> list[KeywordProposal]:
        query = "SELECT * FROM keyword_proposals WHERE 1 = 1"
        params: list[object] = []
        if project is not None:
            query += " AND project = ?"
            params.append(project)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY score DESC, created_at DESC"

        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_proposal(row) for row in rows]

    def get_proposal(self, proposal_id: int) -> KeywordProposal | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM keyword_proposals WHERE id = ?", (proposal_id,)).fetchone()
        return self._row_to_proposal(row) if row else None

    def set_proposal_status(
        self,
        proposal_id: int,
        *,
        status: ProposalStatus,
        reviewer: str | None = None,
        review_note: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE keyword_proposals
                SET status = ?, reviewer = ?, review_note = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (status.value, reviewer, review_note, clock.now().isoformat(), proposal_id),
            )
            conn.commit()

    def approved_overrides(self, *, project: str) -> dict[str, dict[str, object]]:
        overrides: dict[str, dict[str, object]] = {}
        for proposal in self.list_proposals(project=project, status=ProposalStatus.APPROVED):
            product_override = overrides.setdefault(proposal.product_id, {})
            if proposal.kind is ProposalKind.RELAX_REQUIRED_KEYWORDS:
                product_override["required_keywords"] = {"drop": proposal.payload.get("drop_keywords", [])}
                anchor_keywords = proposal.payload.get("anchor_keywords", [])
                if anchor_keywords:
                    product_override["anchor_keywords"] = anchor_keywords
            elif proposal.kind is ProposalKind.ADD_NG_WORDS:
                product_override.setdefault("add_ng_words", [])
                existing = list(product_override["add_ng_words"])
                for token in proposal.payload.get("add_ng_words", []):
                    if token not in existing:
                        existing.append(token)
                product_override["add_ng_words"] = existing
            elif proposal.kind is ProposalKind.ADD_EXCLUDE_PRODUCT_NAMES:
                product_override.setdefault("add_exclude_product_names", [])
                existing = list(product_override["add_exclude_product_names"])
                for name in proposal.payload.get("add_exclude_product_names", []):
                    if name not in existing:
                        existing.append(name)
                product_override["add_exclude_product_names"] = existing
        return overrides

    @staticmethod
    def _row_to_observation(row: sqlite3.Row) -> ObservationRecord:
        return ObservationRecord(
            project=row["project"],
            product_id=row["product_id"],
            product_name=row["product_name"],
            store_name=row["store_name"],
            listing_url=row["listing_url"],
            listing_title=row["listing_title"],
            listing_price=row["listing_price"],
            admitted=bool(row["admitted"]),
            reason=row["reason"],
            missing_keywords=tuple(json.loads(row["missing_keywords_json"])),
            matched_ng_words=tuple(json.loads(row["matched_ng_words_json"])),
            matched_partial_item_words=tuple(json.loads(row["matched_partial_item_words_json"])),
            matched_parts_words=tuple(json.loads(row["matched_parts_words_json"])),
            matched_exclude_product_name=row["matched_exclude_product_name"],
            required_keywords=tuple(json.loads(row["required_keywords_json"])),
            anchor_keywords=tuple(json.loads(row["anchor_keywords_json"])),
            exclude_product_names=tuple(json.loads(row["exclude_product_names_json"])),
            reference_price=row["reference_price"],
            title_normalized=row["title_normalized"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
        )

    @staticmethod
    def _row_to_proposal(row: sqlite3.Row) -> KeywordProposal:
        return KeywordProposal(
            project=row["project"],
            product_id=row["product_id"],
            product_name=row["product_name"],
            kind=ProposalKind(row["kind"]),
            payload=json.loads(row["payload_json"]),
            metrics=json.loads(row["metrics_json"]),
            evidence=json.loads(row["evidence_json"]),
            score=row["score"],
            status=ProposalStatus(row["status"]),
            proposal_id=row["id"],
            reviewer=row["reviewer"],
            review_note=row["review_note"],
            reviewed_at=datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )


def open_keyword_learning_store(db_path: Path) -> KeywordLearningStore:
    return KeywordLearningStore(db_path)
