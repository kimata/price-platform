from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from price_platform.platform import clock
from price_platform.store.fetcher_common import default_keyword_in_title

from .mining import analyze_observations
from .store import open_keyword_learning_store
from .types import ProposalStatus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="price-platform-keyword-learning")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--db", type=Path, required=True)
    analyze.add_argument("--project")
    analyze.add_argument("--min-consecutive-runs", type=int, default=2)

    prune = subparsers.add_parser("prune-observations")
    prune.add_argument("--db", type=Path, required=True)
    prune.add_argument("--project")
    prune.add_argument("--days", type=int, default=90)

    list_cmd = subparsers.add_parser("list-proposals")
    list_cmd.add_argument("--db", type=Path, required=True)
    list_cmd.add_argument("--project")
    list_cmd.add_argument("--status", choices=[status.value for status in ProposalStatus])

    show = subparsers.add_parser("show-proposal")
    show.add_argument("proposal_id", type=int)
    show.add_argument("--db", type=Path, required=True)

    approve = subparsers.add_parser("approve")
    approve.add_argument("proposal_id", type=int)
    approve.add_argument("--db", type=Path, required=True)
    approve.add_argument("--reviewer")
    approve.add_argument("--note")

    reject = subparsers.add_parser("reject")
    reject.add_argument("proposal_id", type=int)
    reject.add_argument("--db", type=Path, required=True)
    reject.add_argument("--reviewer")
    reject.add_argument("--note")

    export = subparsers.add_parser("export-overrides")
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--project", required=True)
    export.add_argument("--out", type=Path, required=True)

    return parser


def _yaml_lines(value: object, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {json.dumps(child, ensure_ascii=False)}")
        return lines
    if isinstance(value, list):
        lines = []
        for child in value:
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}- {json.dumps(child, ensure_ascii=False)}")
        return lines
    return [f"{prefix}{json.dumps(value, ensure_ascii=False)}"]


def main(
    argv: Sequence[str] | None = None,
    *,
    keyword_matcher=default_keyword_in_title,
) -> int:
    args = build_parser().parse_args(argv)
    store = open_keyword_learning_store(args.db)

    if args.command == "analyze":
        records = store.list_observations(project=args.project)
        run_created_at = clock.now()
        prior_payload_counts = store.prior_run_payload_counts(
            project=args.project,
            before_started_at=run_created_at,
        )
        candidate_payloads: set[str] = set()
        proposals = analyze_observations(
            records,
            prior_run_payload_counts=prior_payload_counts,
            keyword_matcher=keyword_matcher,
            candidate_payloads_out=candidate_payloads,
            min_consecutive_runs=args.min_consecutive_runs,
        )
        for proposal in proposals:
            store.upsert_proposal_for_run(proposal, run_created_at=run_created_at)
        store.record_analysis_run(
            project=args.project,
            started_at=run_created_at,
            observation_count=len(records),
            proposal_count=len(proposals),
            candidate_payloads=candidate_payloads,
        )
        print(f"analyzed_records={len(records)}")
        print(f"generated_proposals={len(proposals)}")
        return 0

    if args.command == "prune-observations":
        deleted = store.prune_observations(project=args.project, older_than_days=args.days)
        print(f"deleted_observations={deleted}")
        return 0

    if args.command == "list-proposals":
        status = ProposalStatus(args.status) if args.status else None
        proposals = store.list_proposals(project=args.project, status=status)
        for proposal in proposals:
            print(
                f"{proposal.proposal_id}\t{proposal.project}\t{proposal.product_id}\t"
                f"{proposal.kind.value}\t{proposal.status.value}\t{proposal.score:.3f}"
            )
        return 0

    if args.command == "show-proposal":
        proposal = store.get_proposal(args.proposal_id)
        if proposal is None:
            raise SystemExit(f"proposal not found: {args.proposal_id}")
        print(json.dumps(
            {
                "id": proposal.proposal_id,
                "project": proposal.project,
                "product_id": proposal.product_id,
                "kind": proposal.kind.value,
                "status": proposal.status.value,
                "payload": proposal.payload,
                "metrics": proposal.metrics,
                "evidence": proposal.evidence,
                "score": proposal.score,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ))
        return 0

    if args.command == "approve":
        store.set_proposal_status(
            args.proposal_id,
            status=ProposalStatus.APPROVED,
            reviewer=args.reviewer,
            review_note=args.note,
        )
        return 0

    if args.command == "reject":
        store.set_proposal_status(
            args.proposal_id,
            status=ProposalStatus.REJECTED,
            reviewer=args.reviewer,
            review_note=args.note,
        )
        return 0

    if args.command == "export-overrides":
        overrides = {"products": store.approved_overrides(project=args.project)}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(_yaml_lines(overrides)) + "\n", encoding="utf-8")
        print(args.out)
        return 0

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
