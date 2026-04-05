from __future__ import annotations

import unittest.mock
from pathlib import Path

import price_platform.content.about


def test_load_about_content_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert (
        price_platform.content.about.load_about_content(
            tmp_path / "missing.yaml",
            tmp_path / "schema.yaml",
        )
        is None
    )


def test_load_about_content_parses_loaded_data(monkeypatch, tmp_path: Path) -> None:
    about_file = tmp_path / "about.yaml"
    schema_file = tmp_path / "about.schema.yaml"
    about_file.write_text("dummy")
    schema_file.write_text("dummy")

    monkeypatch.setattr(
        price_platform.content.about.price_platform._adapters,
        "load_yaml_config",
        unittest.mock.create_autospec(
            price_platform.content.about.price_platform._adapters.load_yaml_config,
            return_value={
                "author": {"name": "Kimata", "icon": "/icon.png"},
                "title": "About",
                "description": "Description",
                "introduction": "Intro",
                "site_features": [{"title": "Fast", "description": "Fast enough"}],
                "contact": {"twitter": "@kimata"},
                "affiliate_disclosure": {"title": "Affiliate", "description": "Disclosure"},
            },
        ),
    )

    content = price_platform.content.about.load_about_content(about_file, schema_file)

    assert content is not None
    assert content.author.name == "Kimata"
    assert content.site_features[0].title == "Fast"
    assert content.contact.twitter == "@kimata"
    assert content.affiliate_disclosure is not None
