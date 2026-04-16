from __future__ import annotations

import unittest.mock
from pathlib import Path

import price_platform.content.knowledge

_SAMPLE_ARTICLE_DATA = {
    "id": "focal-length",
    "title": "焦点距離と画角の関係",
    "description": "焦点距離と画角の関係を初心者向けに解説。",
    "hero_text": "> 焦点距離って何?\n\nレンズ選びの基本を解説します。",
    "date_published": "2026-04-12",
    "date_modified": "2026-04-12",
    "primary_keyword": "焦点距離 画角",
    "secondary_keywords": ["焦点距離とは", "画角 広角"],
    "search_intent": "informational",
    "target_audience": "カメラ初心者",
    "tags": ["beginner", "focal-length"],
    "sections": [
        {"title": "焦点距離とは", "content": "焦点距離(mm)は**画角の広さ**を表します。"},
        {"title": "画角とは", "content": "写真に写る範囲の違いを解説。"},
    ],
    "faq": [
        {"question": "焦点距離が長いとボケやすい?", "answer": "はい。**焦点距離**が長いほどボケます。"},
    ],
    "related_guides": ["beginner", "portrait"],
    "related_knowledge": ["f-value-depth-of-field"],
}


def test_knowledge_article_parse() -> None:
    article = price_platform.content.knowledge.KnowledgeArticle.parse(_SAMPLE_ARTICLE_DATA)

    assert article.id == "focal-length"
    assert article.title == "焦点距離と画角の関係"
    assert article.date_published == "2026-04-12"
    assert article.primary_keyword == "焦点距離 画角"
    assert len(article.sections) == 2
    assert article.sections[0].title == "焦点距離とは"
    assert len(article.faq) == 1
    assert article.faq[0].question == "焦点距離が長いとボケやすい?"
    assert article.related_guides == ("beginner", "portrait")
    assert article.related_knowledge == ("f-value-depth-of-field",)
    assert article.tags == ("beginner", "focal-length")


def test_knowledge_article_parse_minimal() -> None:
    minimal = {
        "id": "test",
        "title": "テスト",
        "description": "テスト記事",
        "hero_text": "テスト",
        "sections": [{"title": "セクション", "content": "内容"}],
        "faq": [],
    }
    article = price_platform.content.knowledge.KnowledgeArticle.parse(minimal)

    assert article.id == "test"
    assert article.related_guides == ()
    assert article.related_knowledge == ()
    assert article.date_published is None
    assert article.tags == ()


def test_knowledge_section_parse() -> None:
    section = price_platform.content.knowledge.KnowledgeSection.parse(
        {"title": "タイトル", "content": "**太字**を含む内容"}
    )
    assert section.title == "タイトル"
    assert "**太字**" in section.content


def test_faq_item_parse() -> None:
    faq = price_platform.content.knowledge.FAQItem.parse(
        {"question": "Q?", "answer": "A."}
    )
    assert faq.question == "Q?"
    assert faq.answer == "A."


def test_knowledge_catalog_load(monkeypatch: object, tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "test.yaml").write_text("dummy")

    mock_load = unittest.mock.create_autospec(
        price_platform.content.knowledge.price_platform._adapters.load_yaml_config,
        return_value=_SAMPLE_ARTICLE_DATA,
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        price_platform.content.knowledge.price_platform._adapters,
        "load_yaml_config",
        mock_load,
    )

    catalog = price_platform.content.knowledge.load_knowledge_catalog(knowledge_dir)

    assert catalog.get_by_id("focal-length") is not None
    assert catalog.get_by_id("nonexistent") is None
    assert "focal-length" in catalog.article_ids


def test_knowledge_catalog_get_summaries(monkeypatch: object, tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "test.yaml").write_text("dummy")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        price_platform.content.knowledge.price_platform._adapters,
        "load_yaml_config",
        unittest.mock.create_autospec(
            price_platform.content.knowledge.price_platform._adapters.load_yaml_config,
            return_value=_SAMPLE_ARTICLE_DATA,
        ),
    )

    catalog = price_platform.content.knowledge.load_knowledge_catalog(knowledge_dir)
    summaries = catalog.get_summaries()

    assert len(summaries) == 1
    assert summaries[0].id == "focal-length"
    assert summaries[0].title == "焦点距離と画角の関係"


def test_knowledge_catalog_get_related_summaries(monkeypatch: object, tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "test.yaml").write_text("dummy")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        price_platform.content.knowledge.price_platform._adapters,
        "load_yaml_config",
        unittest.mock.create_autospec(
            price_platform.content.knowledge.price_platform._adapters.load_yaml_config,
            return_value=_SAMPLE_ARTICLE_DATA,
        ),
    )

    catalog = price_platform.content.knowledge.load_knowledge_catalog(knowledge_dir)

    found = catalog.get_related_summaries(["focal-length", "nonexistent"])
    assert len(found) == 1
    assert found[0].id == "focal-length"


def test_knowledge_catalog_last_updates(monkeypatch: object, tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "test.yaml").write_text("dummy")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        price_platform.content.knowledge.price_platform._adapters,
        "load_yaml_config",
        unittest.mock.create_autospec(
            price_platform.content.knowledge.price_platform._adapters.load_yaml_config,
            return_value=_SAMPLE_ARTICLE_DATA,
        ),
    )

    catalog = price_platform.content.knowledge.load_knowledge_catalog(knowledge_dir)
    updates = catalog.last_updates

    assert updates["focal-length"] == "2026-04-12"


def test_knowledge_catalog_empty_dir(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    catalog = price_platform.content.knowledge.load_knowledge_catalog(empty_dir)

    assert catalog.article_ids == []
    assert catalog.get_summaries() == []


def test_knowledge_catalog_missing_dir(tmp_path: Path) -> None:
    catalog = price_platform.content.knowledge.load_knowledge_catalog(tmp_path / "nonexistent")

    assert catalog.article_ids == []


def test_knowledge_catalog_ensure_loaded_raises() -> None:
    catalog = price_platform.content.knowledge.KnowledgeCatalog()
    try:
        catalog.get_summaries()
        assert False, "Expected RuntimeError"
    except RuntimeError:
        pass
