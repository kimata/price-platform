"""Shared content API for price-platform applications."""

from .about import (
    AboutContent,
    AffiliateDisclosure,
    Author,
    Contact,
    SiteFeature,
    load_about_content,
)
from .contact import (
    ContactContent,
    ContactTopic,
    load_contact_content,
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
    "ContactContent",
    "ContactTopic",
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
    "load_contact_content",
    "load_editorial_policy_content",
    "load_knowledge_catalog",
]
