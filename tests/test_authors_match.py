"""
test_authors_match.py — deciding whether one feed item is by a monitored author.

This is the whole of `publication-filter`, and the awkward part of it. The
roster entry carries a stable handle (`id`/`url`, which the validator insists
on), but a publication feed usually credits a bare `dc:creator` NAME. The two
never compare equal as identity keys, so matching has to ask the ladder the
other question: given this person, which observations would resolve TO them?

The answer is their three rungs — the identifier, the canonical profile URL, and
their name scoped to this one publication. Anything else is a non-match, and a
non-match is the SAFE outcome: missing one of Jane's articles costs her a
mention, while a false match credits her with a stranger's work.
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

yaml = pytest.importorskip("yaml", reason="PyYAML required for authors config tests")

from scripts.authors.match import item_matches, match_keys  # noqa: E402
from scripts.authors.model import MonitoredAuthor  # noqa: E402


def _jane(**overrides: object) -> MonitoredAuthor:
    base: dict[str, object] = {
        "name": "Jane Doe",
        "monitoring": "publication-filter",
        "topic": "ai-agents",
        "publication": "example.com",
        "identifier": "orcid:0000-0002-1825-0097",
        "profile_url": "https://example.com/author/jane",
    }
    base.update(overrides)
    return MonitoredAuthor(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# match_keys — the ladder, evaluated from the person outward
# --------------------------------------------------------------------------- #


def test_match_keys_cover_all_three_rungs() -> None:
    keys = match_keys(_jane())
    assert any(k.startswith("id:") for k in keys)
    assert any(k.startswith("url:") for k in keys)
    assert any(k.startswith("name:") and "example.com" in k for k in keys)


def test_name_rung_is_scoped_to_the_publication() -> None:
    # Unscoped, "Jane Doe" would match every Jane Doe on every site the user
    # collects. The scope is what makes the name rung safe to use at all.
    keys = match_keys(_jane())
    assert not any(k == "name:jane doe" for k in keys)


# --------------------------------------------------------------------------- #
# item_matches — the decision made per feed entry
# --------------------------------------------------------------------------- #


def test_matches_on_a_bare_name_from_the_feed() -> None:
    # The common real case: the feed credits "Jane Doe" and nothing else.
    assert item_matches(_jane(), name="Jane Doe", url="", identifier="") is True


def test_name_match_ignores_case_and_spacing() -> None:
    # Spelling, not identity — the same normalisation the ladder already applies.
    assert item_matches(_jane(), name="  jane   DOE ", url="", identifier="") is True


def test_matches_on_the_identifier() -> None:
    assert item_matches(
        _jane(), name="J. Doe", url="", identifier="orcid:0000-0002-1825-0097"
    ) is True


def test_matches_on_the_profile_url() -> None:
    assert item_matches(
        _jane(), name="", url="https://example.com/author/jane", identifier=""
    ) is True


def test_profile_url_match_survives_url_variants() -> None:
    assert item_matches(
        _jane(), name="", url="http://www.example.com/author/jane/", identifier=""
    ) is True


def test_a_different_person_does_not_match() -> None:
    assert item_matches(_jane(), name="John Roe", url="", identifier="") is False


def test_an_uncredited_item_does_not_match() -> None:
    # An article crediting nobody belongs to nobody. Collecting it under Jane's
    # name would be the publication's whole output attributed to one person.
    assert item_matches(_jane(), name="", url="", identifier="") is False


def test_a_different_identifier_does_not_match_despite_the_same_name() -> None:
    # Two people really can share a name; the identifier is the tiebreak, and it
    # says no. Trusting the name here is precisely the harm being avoided.
    assert item_matches(
        _jane(), name="Jane Doe", url="", identifier="orcid:0000-0000-0000-0000"
    ) is False


def test_a_same_named_person_on_another_publication_does_not_match() -> None:
    # The item arrived through a different feed than the one being filtered.
    assert (
        item_matches(_jane(), name="Jane Doe", url="", identifier="", publication="other.test")
        is False
    )


def test_no_fuzzy_name_matching() -> None:
    # "J. Doe", "Jane A. Doe" and "Doe, Jane" are all plausibly her. Guessing is
    # how you eventually credit her with someone else's article.
    for spelling in ("J. Doe", "Jane A. Doe", "Doe, Jane", "Jane"):
        assert item_matches(_jane(), name=spelling, url="", identifier="") is False
