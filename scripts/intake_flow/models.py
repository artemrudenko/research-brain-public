"""Models for read-only URL intake classification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from scripts.content_metadata import AuthorIdentity

Kind = Literal["recurring_source", "one_off_article", "ambiguous"]

CLARIFICATION_QUESTION = (
    "Should I save this one article, or monitor this site for future updates?"
)


@dataclass(frozen=True)
class Preview:
    """The facts behind a verdict, in the form a person can check.

    "recurring_source, confidence 0.90" is accurate and unverifiable. This is what
    the classifier actually saw: the headline, who wrote it, who published it, the
    feed it found. Every field is optional because pages vary — an empty preview
    means the page said nothing, which is itself worth showing.
    """

    title: str = ""
    publication: str = ""
    authors: tuple[AuthorIdentity, ...] = ()
    published_at: str = ""
    feed_url: str = ""
    content_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Only what was established — no empty scaffolding in the JSON."""
        data: dict[str, Any] = {}
        for key in ("title", "publication", "published_at", "feed_url", "content_type"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.authors:
            data["authors"] = [
                {k: v for k, v in (("name", a.name), ("url", a.url), ("id", a.identifier)) if v}
                for a in self.authors
            ]
        return data


@dataclass(frozen=True)
class Classification:
    """Machine-readable result of classifying one URL."""

    input_url: str
    canonical_url: str
    kind: Kind
    confidence: float
    reason: str
    proposed_action: str
    source_url: str | None = None
    source_type: str | None = None
    topic_mode: Literal["existing", "create"] | None = None
    proposed_topic: str | None = None
    clarification_question: str | None = None
    # Additive and always optional: enrichment must never be able to fail a
    # classification, so its absence is a normal state, not an error.
    preview: Preview | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {key: value for key, value in asdict(self).items() if key != "preview"}
        if self.preview is not None:
            data["preview"] = self.preview.to_dict()
        return data
