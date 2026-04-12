"""Knowledge article content models and catalog for price-platform applications.

教育・解説記事（基礎知識）を YAML から読み込んでインデックスするための
データモデルとカタログ。ガイド（購入ガイド）がシーン別の「何を買うか」を
扱うのに対し、知識記事は「なぜ・どうして」の概念解説を扱う。
"""

from __future__ import annotations

import pathlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import price_platform._adapters

_DEFAULT_SCHEMA = pathlib.Path(__file__).parent.parent / "schema" / "knowledge.schema"


@dataclass(frozen=True)
class KnowledgeSection:
    """Article section with title and Markdown content."""

    title: str
    content: str

    @classmethod
    def parse(cls, data: dict[str, Any]) -> KnowledgeSection:
        """Parse from dictionary."""
        return cls(title=data["title"], content=data["content"])


@dataclass(frozen=True)
class FAQItem:
    """FAQ question/answer pair."""

    question: str
    answer: str

    @classmethod
    def parse(cls, data: dict[str, Any]) -> FAQItem:
        """Parse from dictionary."""
        return cls(question=data["question"], answer=data["answer"])


@dataclass(frozen=True)
class KnowledgeArticle:
    """Full knowledge article loaded from YAML."""

    id: str
    title: str
    description: str
    hero_text: str
    sections: tuple[KnowledgeSection, ...]
    faq: tuple[FAQItem, ...]
    related_guides: tuple[str, ...] = ()
    related_knowledge: tuple[str, ...] = ()
    date_published: str | None = None
    date_modified: str | None = None
    primary_keyword: str | None = None
    secondary_keywords: tuple[str, ...] = ()
    search_intent: str | None = None
    target_audience: str | None = None
    tags: tuple[str, ...] = ()

    @classmethod
    def parse(cls, data: dict[str, Any]) -> KnowledgeArticle:
        """Parse from dictionary."""
        parsed = dict(data)
        parsed["sections"] = tuple(KnowledgeSection.parse(s) for s in parsed["sections"])
        parsed["faq"] = tuple(FAQItem.parse(f) for f in parsed.get("faq", []))
        parsed["related_guides"] = tuple(parsed.get("related_guides", []))
        parsed["related_knowledge"] = tuple(parsed.get("related_knowledge", []))
        parsed["secondary_keywords"] = tuple(parsed.get("secondary_keywords", []))
        parsed["tags"] = tuple(parsed.get("tags", []))
        return cls(**parsed)


@dataclass(frozen=True)
class KnowledgeSummary:
    """Lightweight article summary for list views."""

    id: str
    title: str
    description: str


class KnowledgeCatalog:
    """Directory-based knowledge article catalog.

    YAML ディレクトリから記事を読み込み、ID でインデックスする。
    """

    def __init__(self) -> None:
        self._articles: dict[str, KnowledgeArticle] = {}
        self._loaded: bool = False

    def load(
        self,
        knowledge_dir: pathlib.Path,
        schema_file: pathlib.Path | None = None,
    ) -> None:
        """Load all YAML files from directory."""
        schema = schema_file or _DEFAULT_SCHEMA

        if not knowledge_dir.is_dir():
            self._loaded = True
            return

        for yaml_file in sorted(knowledge_dir.glob("*.yaml")):
            data = price_platform._adapters.load_yaml_config(
                yaml_file, schema, include_base_dir=False
            )
            if data is None:
                continue
            article = KnowledgeArticle.parse(data)
            self._articles[article.id] = article

        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            msg = "KnowledgeCatalog.load() must be called before accessing articles"
            raise RuntimeError(msg)

    def get_by_id(self, article_id: str) -> KnowledgeArticle | None:
        """Get article by ID, or None if not found."""
        self._ensure_loaded()
        return self._articles.get(article_id)

    def get_summaries(self) -> list[KnowledgeSummary]:
        """Get summaries of all articles."""
        self._ensure_loaded()
        return [
            KnowledgeSummary(id=a.id, title=a.title, description=a.description)
            for a in self._articles.values()
        ]

    def get_related_summaries(self, article_ids: Sequence[str]) -> list[KnowledgeSummary]:
        """Get summaries for the given article IDs (skipping unknown IDs)."""
        self._ensure_loaded()
        result: list[KnowledgeSummary] = []
        for aid in article_ids:
            article = self._articles.get(aid)
            if article is not None:
                result.append(KnowledgeSummary(id=article.id, title=article.title, description=article.description))
        return result

    @property
    def article_ids(self) -> list[str]:
        """List of all article IDs."""
        self._ensure_loaded()
        return list(self._articles.keys())

    @property
    def last_updates(self) -> dict[str, str | None]:
        """Map of article ID to date_modified (or date_published)."""
        self._ensure_loaded()
        return {
            a.id: a.date_modified or a.date_published
            for a in self._articles.values()
        }


def load_knowledge_catalog(
    knowledge_dir: pathlib.Path,
    schema_file: pathlib.Path | None = None,
) -> KnowledgeCatalog:
    """Create and load a KnowledgeCatalog from a directory of YAML files."""
    catalog = KnowledgeCatalog()
    catalog.load(knowledge_dir, schema_file)
    return catalog
