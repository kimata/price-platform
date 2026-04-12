"""Shared content API for price-platform applications."""

from .about import (
    AboutContent,
    AffiliateDisclosure,
    Author,
    Contact,
    SiteFeature,
    load_about_content,
)
from .editorial import (
    EditorialPolicyContent,
    EditorialPrinciple,
    EditorialWorkflowStep,
    load_editorial_policy_content,
)
from .knowledge import (
    FAQItem,
    KnowledgeArticle,
    KnowledgeCatalog,
    KnowledgeSection,
    KnowledgeSummary,
    load_knowledge_catalog,
)

__all__ = [
    "AboutContent",
    "AffiliateDisclosure",
    "Author",
    "Contact",
    "EditorialPolicyContent",
    "EditorialPrinciple",
    "EditorialWorkflowStep",
    "FAQItem",
    "KnowledgeArticle",
    "KnowledgeCatalog",
    "KnowledgeSection",
    "KnowledgeSummary",
    "SiteFeature",
    "load_about_content",
    "load_editorial_policy_content",
    "load_knowledge_catalog",
]
