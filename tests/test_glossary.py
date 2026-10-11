"""
test_glossary.py — offline tests for the deterministic digest glossary.

The glossary appends plain-language explanations for jargon that ACTUALLY appears
in a digest, reading the curated `config/glossary.yaml`. All tests are
self-contained (tmp files, no network).
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import glossary as gl  # noqa: E402

_TERMS = {
    "LLM": "Large Language Model — trained on text to understand and generate language.",
    "RAG": "Retrieval-Augmented Generation — fetch documents, then let the model answer.",
    "API": "Application Programming Interface — a defined way for programs to call each other.",
}


def _write_glossary(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "glossary.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# load_glossary
# --------------------------------------------------------------------------- #


def test_load_glossary_reads_terms_map(tmp_path: Path) -> None:
    path = _write_glossary(
        tmp_path,
        'terms:\n  LLM: "Large Language Model"\n  RAG: "Retrieval-Augmented Generation"\n',
    )
    assert gl.load_glossary(path) == {
        "LLM": "Large Language Model",
        "RAG": "Retrieval-Augmented Generation",
    }


def test_load_glossary_missing_file_is_empty(tmp_path: Path) -> None:
    assert gl.load_glossary(tmp_path / "nope.yaml") == {}


def test_load_glossary_missing_file_is_silent(
    tmp_path: Path, capsys: "pytest.CaptureFixture[str]"
) -> None:
    # An absent glossary is a supported configuration (delete the file to turn
    # the feature off) — it must not nag on stderr.
    gl.load_glossary(tmp_path / "nope.yaml")
    assert capsys.readouterr().err == ""


def test_load_glossary_broken_yaml_warns_and_returns_empty(
    tmp_path: Path, capsys: "pytest.CaptureFixture[str]"
) -> None:
    # A parse error must stay non-fatal (the glossary is best-effort), but it
    # must WARN on stderr — a YAML typo silently disabling the glossary is a
    # debugging trap.
    path = _write_glossary(tmp_path, "terms: [unclosed\n")
    assert gl.load_glossary(path) == {}
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "glossary" in err


def test_load_glossary_without_pyyaml_falls_back_to_line_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On the headless runtime PyYAML is often absent (bare system python3). The
    # loader must NOT silently degrade to empty — that would strip the glossary
    # from every headless digest and turn the "uncovered acronyms" warning into
    # noise flagging terms the file DOES define (the same failure mode as the
    # tags.yaml BUG 1). Instead it falls back to a dependency-free line parser.
    path = _write_glossary(
        tmp_path,
        "# a header comment\n"
        "terms:\n"
        "  # ── section header comment ──\n"
        '  LLM: "Large Language Model — text in, text out."\n'
        '  CI/CD: "Continuous Integration / Continuous Delivery — ship safely."\n'
        "\n"
        '  RAG: "Retrieval-Augmented Generation: ground answers in sources."\n',
    )
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def no_yaml(name: str, *args: object, **kwargs: object):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_yaml)
    terms = gl.load_glossary(path)
    assert terms == {
        "LLM": "Large Language Model — text in, text out.",
        "CI/CD": "Continuous Integration / Continuous Delivery — ship safely.",
        # A colon INSIDE the quoted value must not truncate it.
        "RAG": "Retrieval-Augmented Generation: ground answers in sources.",
    }
    # Insertion order is preserved (the rendered section follows file order).
    assert list(terms) == ["LLM", "CI/CD", "RAG"]


def test_parse_glossary_lines_scopes_to_terms_block() -> None:
    # Only the `terms:` block is read: keys before it and any NEXT top-level key
    # are ignored, an empty value is skipped (PyYAML would yield None -> filtered),
    # and unquoted values are taken as-is.
    text = (
        "version: 1\n"
        "terms:\n"
        "  API: Application Programming Interface\n"
        "  EMPTY:\n"
        "other:\n"
        '  NOT: "not a term"\n'
    )
    assert gl._parse_glossary_lines(text) == {
        "API": "Application Programming Interface",
    }


def test_parse_glossary_lines_matches_pyyaml_on_shipped_file() -> None:
    # Parity guarantee on the REAL shipped config: the fallback and PyYAML must
    # read config/glossary.yaml identically (same terms, same order), so a
    # headless install renders exactly the glossary the agent path does.
    yaml = pytest.importorskip("yaml")
    shipped = _PROJECT_ROOT / "config" / "glossary.yaml"
    text = shipped.read_text(encoding="utf-8")
    via_yaml = {
        str(k): str(v)
        for k, v in yaml.safe_load(text)["terms"].items()
        if isinstance(k, str) and k.strip() and isinstance(v, str)
    }
    via_fallback = gl._parse_glossary_lines(text)
    assert via_fallback == via_yaml
    assert list(via_fallback) == list(via_yaml)


def test_load_glossary_malformed_shape_is_empty(tmp_path: Path) -> None:
    # A top-level list (no `terms:` map) must degrade to empty, not crash.
    path = _write_glossary(tmp_path, "- just\n- a\n- list\n")
    assert gl.load_glossary(path) == {}


def test_load_glossary_skips_non_string_entries(tmp_path: Path) -> None:
    path = _write_glossary(
        tmp_path,
        'terms:\n  LLM: "ok"\n  BAD:\n    nested: value\n',
    )
    assert gl.load_glossary(path) == {"LLM": "ok"}


# --------------------------------------------------------------------------- #
# glossary_section — matching & rendering
# --------------------------------------------------------------------------- #


def test_section_lists_only_terms_that_appear() -> None:
    text = "We deployed a RAG pipeline using an LLM. No mention of the other one."
    section = gl.glossary_section(text, _TERMS)
    assert section.startswith("## 📖 Glossary")
    assert "**LLM**" in section
    assert "**RAG**" in section
    assert "**API**" not in section  # API never appears in the text


def test_section_preserves_glossary_order() -> None:
    # Text mentions RAG before LLM, but the section follows glossary order (LLM first).
    text = "RAG and LLM both matter."
    section = gl.glossary_section(text, _TERMS)
    assert section.index("**LLM**") < section.index("**RAG**")


def test_section_empty_when_no_term_present() -> None:
    assert gl.glossary_section("nothing technical here at all", _TERMS) == ""


def test_matching_is_whole_word() -> None:
    # "API" must not fire inside "capital"; "RAG" must not fire inside "storage".
    assert gl.glossary_section("capital storage decisions", _TERMS) == ""


def test_matching_is_case_sensitive() -> None:
    # Lowercase "llm" / "rag" do not match the uppercase acronym keys.
    assert gl.glossary_section("a small llm and some rag", _TERMS) == ""


def test_matching_allows_trailing_plural_s() -> None:
    section = gl.glossary_section("several LLMs and many APIs", _TERMS)
    assert "**LLM**" in section
    assert "**API**" in section


# --------------------------------------------------------------------------- #
# uncovered_acronyms — sufficiency detector
# --------------------------------------------------------------------------- #


def test_uncovered_flags_acronyms_absent_from_glossary() -> None:
    # LoRA and PEFT are jargon the glossary does not define; RAG is covered.
    text = "LoRA and PEFT extend plain RAG for cheaper fine-tuning."
    assert gl.uncovered_acronyms(text, _TERMS) == ["LoRA", "PEFT"]


def test_uncovered_excludes_covered_terms() -> None:
    text = "We shipped an LLM behind an API with RAG."
    assert gl.uncovered_acronyms(text, _TERMS) == []


def test_uncovered_ignores_plain_words() -> None:
    assert gl.uncovered_acronyms("the system is fast and reliable today", _TERMS) == []


def test_uncovered_normalizes_trailing_plural() -> None:
    # "GPUs" is reported once as its singular acronym, not "GPUs".
    assert gl.uncovered_acronyms("many GPUs and several TPUs", _TERMS) == ["GPU", "TPU"]


def test_uncovered_treats_slashed_acronym_as_one_token() -> None:
    # "CI/CD" is a single covered term, so neither half is flagged.
    terms = {"CI/CD": "continuous integration / continuous delivery"}
    assert gl.uncovered_acronyms("our CI/CD pipeline", terms) == []


def test_uncovered_is_deduped_and_sorted() -> None:
    text = "PEFT here, PEFT there, and AEO everywhere."
    assert gl.uncovered_acronyms(text, {}) == ["AEO", "PEFT"]


def test_uncovered_ignores_wellknown_company_names() -> None:
    # Vendor names are proper nouns, not jargon a reader needs defined — they
    # must not pad the "uncovered" warning on every industry-news digest.
    text = "IBM and HP partner with OpenAI; SDD remains uncovered."
    assert gl.uncovered_acronyms(text, {}) == ["SDD"]


def test_uncovered_skips_common_non_jargon_caps() -> None:
    # Everyday capitalised tokens are not glossary candidates.
    assert gl.uncovered_acronyms("OK the US and UK agreed", {}) == []


# --------------------------------------------------------------------------- #
# shipped config coverage — the real glossary must define the acronyms our
# topics actually surface (regression guard against under-coverage).
# --------------------------------------------------------------------------- #


def test_shipped_glossary_covers_current_domain_acronyms() -> None:
    shipped = gl.load_glossary(_PROJECT_ROOT / "config" / "glossary.yaml")
    for term in ("AEO", "EUV", "LoRA", "PEFT", "RL", "JVM", "CRM", "TPU"):
        assert term in shipped, f"glossary is missing '{term}'"


# --------------------------------------------------------------------------- #
# append_glossary
# --------------------------------------------------------------------------- #


def test_append_adds_section_for_used_terms(tmp_path: Path) -> None:
    path = _write_glossary(tmp_path, 'terms:\n  LLM: "Large Language Model"\n')
    out = gl.append_glossary("# Digest\n\nWe used an LLM.\n", path)
    assert out.rstrip().endswith("- **LLM** — Large Language Model")
    assert "## 📖 Glossary" in out


def test_append_is_noop_when_nothing_matches(tmp_path: Path) -> None:
    path = _write_glossary(tmp_path, 'terms:\n  LLM: "Large Language Model"\n')
    original = "# Digest\n\nA plain note with no jargon.\n"
    assert gl.append_glossary(original, path) == original


def test_append_is_noop_when_glossary_missing(tmp_path: Path) -> None:
    original = "# Digest\n\nWe used an LLM.\n"
    assert gl.append_glossary(original, tmp_path / "absent.yaml") == original
