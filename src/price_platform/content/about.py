"""About content models and loaders for price-platform applications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import price_platform._adapters


@dataclass(frozen=True)
class Author:
    """Author information."""

    name: str
    icon: str

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Author:
        """Parse from dictionary."""
        return cls(name=data["name"], icon=data["icon"])


@dataclass(frozen=True)
class SiteFeature:
    """Site feature item."""

    title: str
    description: str

    @classmethod
    def parse(cls, data: dict[str, Any]) -> SiteFeature:
        """Parse from dictionary."""
        return cls(title=data["title"], description=data["description"])


@dataclass(frozen=True)
class Contact:
    """Contact information."""

    twitter: str | None = None
    message: str | None = None

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> Contact:
        """Parse from dictionary."""
        if data is None:
            return cls()
        return cls(**data)


@dataclass(frozen=True)
class AffiliateDisclosure:
    """Affiliate disclosure information."""

    title: str
    description: str

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> AffiliateDisclosure | None:
        """Parse from dictionary."""
        if data is None:
            return None
        return cls(title=data["title"], description=data["description"])


@dataclass(frozen=True)
class AboutContent:
    """About page content."""

    author: Author
    title: str
    description: str
    introduction: str
    site_features: tuple[SiteFeature, ...] = field(default_factory=tuple)
    contact: Contact = field(default_factory=Contact)
    affiliate_disclosure: AffiliateDisclosure | None = None

    @classmethod
    def parse(cls, data: dict[str, Any]) -> AboutContent:
        """Parse from dictionary."""
        parsed = dict(data)
        parsed["author"] = Author.parse(parsed["author"])
        if "site_features" in parsed:
            parsed["site_features"] = tuple(SiteFeature.parse(item) for item in parsed["site_features"])
        parsed["contact"] = Contact.parse(parsed.get("contact"))
        parsed["affiliate_disclosure"] = AffiliateDisclosure.parse(parsed.get("affiliate_disclosure"))
        return cls(**parsed)


def load_about_content(about_file: Path, schema_file: Path) -> AboutContent | None:
    """Load about content from YAML file."""
    if not about_file.exists():
        return None

    data = price_platform._adapters.load_yaml_config(about_file, schema_file, include_base_dir=False)
    if data is None:
        return None

    return AboutContent.parse(data)
