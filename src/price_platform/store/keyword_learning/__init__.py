"""Keyword learning helpers for product-name filter refinement."""

from .cli import main as cli_main
from .mining import analyze_observations
from .scoring import score_observation
from .store import KeywordLearningStore, open_keyword_learning_store
from .types import (
    AnalysisWindow,
    FilterObservationContext,
    KeywordProposal,
    ProposalKind,
    ProposalStatus,
)

__all__ = [
    "AnalysisWindow",
    "FilterObservationContext",
    "KeywordLearningStore",
    "KeywordProposal",
    "ProposalKind",
    "ProposalStatus",
    "analyze_observations",
    "cli_main",
    "open_keyword_learning_store",
    "score_observation",
]
