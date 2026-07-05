from __future__ import annotations

import unittest.mock
from pathlib import Path

import price_platform.content.contact


def test_load_contact_content_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert (
        price_platform.content.contact.load_contact_content(
            tmp_path / "missing.yaml",
            tmp_path / "schema.yaml",
        )
        is None
    )


def test_load_contact_content_parses_loaded_data(monkeypatch, tmp_path: Path) -> None:
    contact_file = tmp_path / "contact.yaml"
    schema_file = tmp_path / "contact.schema.yaml"
    contact_file.write_text("dummy")
    schema_file.write_text("dummy")

    monkeypatch.setattr(
        price_platform.content.contact.price_platform._adapters,
        "load_yaml_config",
        unittest.mock.create_autospec(
            price_platform.content.contact.price_platform._adapters.load_yaml_config,
            return_value={
                "title": "お問い合わせ",
                "description": "掲載情報に関するお問い合わせ",
                "introduction": "フォームからご連絡ください。",
                "form_url": "https://docs.google.com/forms/d/e/xxx/viewform",
                "twitter": "@example",
                "topics": [
                    {"title": "掲載情報の誤り", "description": "価格やスペックの誤りのご指摘"},
                ],
                "response_notes": ["すべてのお問い合わせに返信できない場合があります。"],
            },
        ),
    )

    content = price_platform.content.contact.load_contact_content(contact_file, schema_file)

    assert content is not None
    assert content.title == "お問い合わせ"
    assert content.form_url == "https://docs.google.com/forms/d/e/xxx/viewform"
    assert content.email is None
    assert content.topics[0].title == "掲載情報の誤り"
    assert content.response_notes == ("すべてのお問い合わせに返信できない場合があります。",)


def test_load_contact_content_minimal_fields(monkeypatch, tmp_path: Path) -> None:
    contact_file = tmp_path / "contact.yaml"
    contact_file.write_text("dummy")

    monkeypatch.setattr(
        price_platform.content.contact.price_platform._adapters,
        "load_yaml_config",
        unittest.mock.create_autospec(
            price_platform.content.contact.price_platform._adapters.load_yaml_config,
            return_value={
                "title": "お問い合わせ",
                "description": "説明",
                "introduction": "本文",
            },
        ),
    )

    content = price_platform.content.contact.load_contact_content(contact_file)

    assert content is not None
    assert content.form_url is None
    assert content.topics == ()
    assert content.response_notes == ()
