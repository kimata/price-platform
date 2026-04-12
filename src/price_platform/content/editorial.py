"""Editorial and trust content models for price-platform applications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import price_platform._adapters

_DEFAULT_SCHEMA = Path(__file__).parent.parent / "schema" / "editorial_policy.schema"


@dataclass(frozen=True)
class EditorialPrinciple:
    """A concise editorial principle."""

    title: str
    description: str

    @classmethod
    def parse(cls, data: dict[str, Any]) -> EditorialPrinciple:
        return cls(title=data["title"], description=data["description"])


@dataclass(frozen=True)
class EditorialWorkflowStep:
    """A single data or review workflow step."""

    title: str
    description: str

    @classmethod
    def parse(cls, data: dict[str, Any]) -> EditorialWorkflowStep:
        return cls(title=data["title"], description=data["description"])


@dataclass(frozen=True)
class EditorialPolicyContent:
    """Editorial policy page content."""

    title: str
    description: str
    overview: str
    principles: tuple[EditorialPrinciple, ...] = field(default_factory=tuple)
    methodology: tuple[EditorialWorkflowStep, ...] = field(default_factory=tuple)
    update_policy: tuple[str, ...] = field(default_factory=tuple)
    monetization_policy: tuple[str, ...] = field(default_factory=tuple)
    correction_policy: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> EditorialPolicyContent:
        parsed = dict(data)
        parsed["principles"] = tuple(
            EditorialPrinciple.parse(item) for item in parsed.get("principles", [])
        )
        parsed["methodology"] = tuple(
            EditorialWorkflowStep.parse(item) for item in parsed.get("methodology", [])
        )
        parsed["update_policy"] = tuple(parsed.get("update_policy", []))
        parsed["monetization_policy"] = tuple(parsed.get("monetization_policy", []))
        parsed["correction_policy"] = tuple(parsed.get("correction_policy", []))
        return cls(**parsed)


def load_editorial_policy_content(
    policy_file: Path,
    schema_file: Path | None = None,
) -> EditorialPolicyContent | None:
    """Load editorial policy content from YAML file."""
    if not policy_file.exists():
        return None

    data = price_platform._adapters.load_yaml_config(
        policy_file, schema_file or _DEFAULT_SCHEMA, include_base_dir=False
    )
    if data is None:
        return None

    return EditorialPolicyContent.parse(data)
