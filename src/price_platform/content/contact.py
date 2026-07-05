"""Contact page content models for price-platform applications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import price_platform._adapters

_DEFAULT_SCHEMA = Path(__file__).parent.parent / "schema" / "contact.schema"


@dataclass(frozen=True)
class ContactTopic:
    """An inquiry topic accepted via the contact page."""

    title: str
    description: str

    @classmethod
    def parse(cls, data: dict[str, Any]) -> ContactTopic:
        return cls(title=data["title"], description=data["description"])


@dataclass(frozen=True)
class ContactContent:
    """Contact page content."""

    title: str
    description: str
    introduction: str
    form_url: str | None = None
    email: str | None = None
    twitter: str | None = None
    topics: tuple[ContactTopic, ...] = field(default_factory=tuple)
    response_notes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> ContactContent:
        parsed = dict(data)
        parsed["topics"] = tuple(ContactTopic.parse(item) for item in parsed.get("topics", []))
        parsed["response_notes"] = tuple(parsed.get("response_notes", []))
        return cls(**parsed)


def load_contact_content(
    contact_file: Path,
    schema_file: Path | None = None,
) -> ContactContent | None:
    """Load contact page content from YAML file."""
    if not contact_file.exists():
        return None

    data = price_platform._adapters.load_yaml_config(
        contact_file, schema_file or _DEFAULT_SCHEMA, include_base_dir=False
    )
    if data is None:
        return None

    return ContactContent.parse(data)
