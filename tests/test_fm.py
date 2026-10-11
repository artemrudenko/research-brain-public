"""Tests for scripts/fm.py — the shared Markdown frontmatter reader.

fm.py is the single owner of the `---`…`---` boundary rule and the PyYAML/stdlib
parse fallback that used to live as near-identical copies across the pipeline.
These tests pin the boundary edge-cases (unclosed fence, a `----` line that must
NOT close, empty frontmatter) and the yaml/no-yaml parity that lets the headless
runtime read frontmatter without PyYAML.
"""

from __future__ import annotations

import sys

from scripts import extract_vault_notes as evn  # noqa: E402
from scripts import fm  # noqa: E402

# ── split_frontmatter ─────────────────────────────────────────────────────── #


def test_split_no_fence_is_all_body() -> None:
    assert fm.split_frontmatter("# Title\nbody") == ("", "# Title\nbody")


def test_split_closed_fence_excludes_both_fences() -> None:
    text = "---\ntitle: x\ntags: [a]\n---\nbody line\n"
    block, body = fm.split_frontmatter(text)
    assert block == "title: x\ntags: [a]"
    # splitlines() drops the trailing newline — body is the joined body lines.
    assert body == "body line"


def test_split_unclosed_fence_is_all_body() -> None:
    text = "---\ntitle: x\nno closing fence"
    assert fm.split_frontmatter(text) == ("", text)


def test_split_a_dashed_line_that_is_not_exactly_a_fence_does_not_close() -> None:
    # A line that merely STARTS with --- (e.g. `----`) must not close the block.
    text = "---\ntitle: x\n----\n---\nbody"
    block, body = fm.split_frontmatter(text)
    assert block == "title: x\n----"
    assert body == "body"


def test_split_empty_frontmatter_block() -> None:
    assert fm.split_frontmatter("---\n---\nbody") == ("", "body")


def test_split_closing_fence_tolerates_trailing_space() -> None:
    # `--- ` strips to `---`, so it closes the block.
    block, body = fm.split_frontmatter("---\nk: v\n--- \nbody")
    assert block == "k: v"
    assert body == "body"


# ── parse_scalars (flat key: value, stdlib only) ──────────────────────────── #


def test_parse_scalars_flat_pairs() -> None:
    assert fm.parse_scalars("title: Hello\ncategory: ai") == {
        "title": "Hello",
        "category": "ai",
    }


def test_parse_scalars_ignores_lines_without_a_colon() -> None:
    assert fm.parse_scalars("title: x\ngarbage line\nk: v") == {"title": "x", "k": "v"}


def test_parse_scalars_keeps_colon_in_value() -> None:
    assert fm.parse_scalars("url: https://x.co/a") == {"url": "https://x.co/a"}


def test_parse_scalars_last_key_wins() -> None:
    assert fm.parse_scalars("k: a\nk: b") == {"k": "b"}


def test_parse_scalars_empty_block() -> None:
    assert fm.parse_scalars("") == {}


# ── parse_frontmatter (PyYAML path) ───────────────────────────────────────── #


def test_parse_frontmatter_empty_is_empty_dict() -> None:
    assert fm.parse_frontmatter("") == {}
    assert fm.parse_frontmatter("   \n  ") == {}


def test_parse_frontmatter_scalars_and_lists() -> None:
    block = 'title: X\ntags:\n  - ai\n  - tech\nrelated_concept: ["[[a]]", "[[b]]"]'
    data = fm.parse_frontmatter(block)
    assert data["title"] == "X"
    assert data["tags"] == ["ai", "tech"]
    assert data["related_concept"] == ["[[a]]", "[[b]]"]


def test_parse_frontmatter_non_mapping_is_empty_dict() -> None:
    assert fm.parse_frontmatter("- just\n- a bare list") == {}


# ── yaml / no-yaml fallback parity ────────────────────────────────────────── #


def test_parse_frontmatter_falls_back_when_pyyaml_is_absent(monkeypatch) -> None:
    # Setting sys.modules['yaml'] = None makes `import yaml` raise ImportError,
    # forcing parse_frontmatter down its dependency-free path.
    monkeypatch.setitem(sys.modules, "yaml", None)
    block = (
        'title: X\n'
        "tags: [ai, tech]\n"
        "related_concept:\n"
        '  - "[[a]]"\n'
        "sources:\n"
        "  - url: http://a\n"
    )
    data = fm.parse_frontmatter(block)
    assert data["title"] == "X"
    # Inline lists strip quotes; block-list items are kept verbatim (quotes and
    # all) — downstream readers strip them when resolving. This asymmetry is
    # pre-existing behavior the shared reader preserves exactly.
    assert data["tags"] == ["ai", "tech"]
    assert data["related_concept"] == ['"[[a]]"']
    # A block-mapping list item is captured as a non-empty marker (emptiness
    # checks work; inner fields are not needed by the readers).
    assert data["sources"]


def test_fallback_inline_list_strips_quotes() -> None:
    got = fm._parse_frontmatter_fallback('tags: ["ai/agents", "tech/news"]')
    assert got["tags"] == ["ai/agents", "tech/news"]


def test_fallback_scalar_strips_a_matching_quote_pair() -> None:
    assert fm._parse_frontmatter_fallback('title: "Hello World"')["title"] == "Hello World"


def test_fallback_round_trips_yaml_quote_escaped_titles(monkeypatch) -> None:
    # extract_vault_notes._yaml_quote escapes `\` and `"` when writing a quoted
    # scalar; the dependency-free fallback must reverse exactly those escapes or
    # quoted lesson titles reach readers with stray backslashes (the PyYAML path
    # already decodes them — this pins the two paths to the same answer).
    monkeypatch.setitem(sys.modules, "yaml", None)
    title = 'Title patterns are engine-specific: "What is X" wins, C:\\paths lose'
    block = f"title: {evn._yaml_quote(title)}"
    assert fm.parse_frontmatter(block)["title"] == title


def test_fallback_leaves_single_quoted_scalars_verbatim() -> None:
    # YAML single-quoted scalars escape via `''`, never backslashes — a backslash
    # between single quotes is content and must survive untouched.
    got = fm._parse_frontmatter_fallback(r"title: 'keep \" and \\ as-is'")
    assert got["title"] == r'keep \" and \\ as-is'


def test_fallback_skips_comments_and_indented_keys() -> None:
    assert fm._parse_frontmatter_fallback("# comment\ntitle: x\n  nested: y") == {"title": "x"}


# ── insert_after_frontmatter ──────────────────────────────────────────────── #


def test_insert_after_frontmatter_splices_after_closing_fence() -> None:
    text = "---\ntitle: x\n---\nbody\n"
    out = fm.insert_after_frontmatter(text, "INSERTED")
    assert out == "---\ntitle: x\n---\n\nINSERTED\nbody\n"


def test_insert_after_frontmatter_preserves_absent_trailing_newline() -> None:
    text = "---\ntitle: x\n---\nbody"  # no trailing newline
    out = fm.insert_after_frontmatter(text, "INSERTED")
    assert out == "---\ntitle: x\n---\n\nINSERTED\nbody"
    assert not out.endswith("\n")


def test_insert_after_frontmatter_prepends_when_no_frontmatter() -> None:
    assert fm.insert_after_frontmatter("just body", "INSERTED") == "INSERTED\n\njust body"


def test_insert_after_frontmatter_unclosed_fence_prepends() -> None:
    # An opening `---` with no closing fence is treated as no frontmatter.
    text = "---\ntitle: x\nno close"
    assert fm.insert_after_frontmatter(text, "INSERTED") == "INSERTED\n\n" + text
