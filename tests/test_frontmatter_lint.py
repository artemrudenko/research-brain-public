"""
test_frontmatter_lint.py — offline tests for the SKILL.md frontmatter linter.

`scripts/frontmatter_lint.py` checks each `skills/*/SKILL.md` for a well-formed
YAML frontmatter block carrying the required `name` / `description` keys (and a
kebab-case `name`). It runs warn-only by default (exit 0) and as a blocking gate
under `--enforce` (exit 1 on any violation). These tests build self-contained
fake skill dirs under a tmp path, so the real `skills/` tree is never touched.
"""
import sys
from pathlib import Path

from scripts import frontmatter_lint as fl  # noqa: E402


def _skill(skills_dir: Path, name: str, body: str) -> Path:
    """Write a `skills/<name>/SKILL.md` with the given raw body; return its path."""
    path = skills_dir / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    return path


_CLEAN = "---\nname: foo-bar\ndescription: Does the foo.\n---\n\n# Foo\n"


# --------------------------------------------------------------------------- #
# frontmatter_block
# --------------------------------------------------------------------------- #


def test_frontmatter_block_extracts_between_fences():
    assert "name: foo-bar" in fl.frontmatter_block(_CLEAN)


def test_frontmatter_block_absent_when_no_leading_fence():
    assert fl.frontmatter_block("# Title\n\nbody\n") == ""


def test_frontmatter_block_absent_when_unterminated():
    # A leading `---` with no closing fence is not a valid block.
    assert fl.frontmatter_block("---\nname: x\n") == ""


# --------------------------------------------------------------------------- #
# field
# --------------------------------------------------------------------------- #


def test_field_reads_value():
    assert fl.field("name: foo-bar\ndescription: hi", "name") == "foo-bar"


def test_field_strips_quotes():
    assert fl.field('name: "foo-bar"', "name") == "foo-bar"


def test_field_missing_key_is_none():
    assert fl.field("description: hi", "name") is None


def test_field_empty_value_is_none():
    assert fl.field("name:   ", "name") is None


# --------------------------------------------------------------------------- #
# lint_file
# --------------------------------------------------------------------------- #


def test_lint_file_clean(tmp_path: Path):
    path = _skill(tmp_path, "foo-bar", _CLEAN)
    assert fl.lint_file(path) == []


def test_lint_file_missing_block(tmp_path: Path):
    path = _skill(tmp_path, "foo", "# Foo\n\nno frontmatter\n")
    warnings = fl.lint_file(path)
    assert any("missing YAML frontmatter block" in w for w in warnings)


def test_lint_file_missing_required_key(tmp_path: Path):
    path = _skill(tmp_path, "foo", "---\nname: foo\n---\n")
    warnings = fl.lint_file(path)
    assert any("missing required key `description`" in w for w in warnings)


def test_lint_file_bad_name_not_kebab(tmp_path: Path):
    path = _skill(tmp_path, "foo", "---\nname: Foo_Bar\ndescription: hi\n---\n")
    warnings = fl.lint_file(path)
    assert any("not kebab-case" in w for w in warnings)


def test_lint_file_name_too_many_words(tmp_path: Path):
    path = _skill(tmp_path, "foo", "---\nname: a-b-c-d\ndescription: hi\n---\n")
    warnings = fl.lint_file(path)
    assert any("not kebab-case" in w for w in warnings)


# --------------------------------------------------------------------------- #
# iter_skill_files
# --------------------------------------------------------------------------- #


def test_iter_skill_files_absent_dir_yields_nothing(tmp_path: Path):
    assert list(fl.iter_skill_files(tmp_path / "missing")) == []


def test_iter_skill_files_sorted(tmp_path: Path):
    _skill(tmp_path, "b-skill", _CLEAN)
    _skill(tmp_path, "a-skill", _CLEAN)
    found = [p.parent.name for p in fl.iter_skill_files(tmp_path)]
    assert found == ["a-skill", "b-skill"]


# --------------------------------------------------------------------------- #
# _relpath
# --------------------------------------------------------------------------- #


def test_relpath_outside_root_returns_str(tmp_path: Path):
    # A path outside PROJECT_ROOT can't be made relative -> fall back to str.
    outside = tmp_path / "x" / "SKILL.md"
    assert fl._relpath(outside) == str(outside)


# --------------------------------------------------------------------------- #
# main() — CLI modes
# --------------------------------------------------------------------------- #


def _run(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["frontmatter_lint.py", *argv])
    return fl.main()


def test_main_warn_only_exits_zero_despite_violations(tmp_path, monkeypatch, capsys):
    _skill(tmp_path, "foo", "# no frontmatter\n")
    code = _run(monkeypatch, [str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "warn-only" in out
    assert "violations=1" in out


def test_main_enforce_clean_exits_zero(tmp_path, monkeypatch, capsys):
    _skill(tmp_path, "foo-bar", _CLEAN)
    code = _run(monkeypatch, [str(tmp_path), "--enforce"])
    assert code == 0
    assert "enforce: clean" in capsys.readouterr().out


def test_main_enforce_with_violations_exits_one(tmp_path, monkeypatch, capsys):
    _skill(tmp_path, "foo", "# no frontmatter\n")
    code = _run(monkeypatch, [str(tmp_path), "--enforce"])
    assert code == 1
    assert "BLOCKING" in capsys.readouterr().out


def test_main_json_output(tmp_path, monkeypatch, capsys):
    import json

    _skill(tmp_path, "foo", "# no frontmatter\n")
    code = _run(monkeypatch, [str(tmp_path), "--enforce", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["scanned"] == 1
    assert payload["violations"] == 1
    assert payload["blocking"] is True
    assert payload["mode"] == "enforce"


def test_main_relative_dir_resolves_under_project_root(monkeypatch, capsys):
    # A relative SKILLS_DIR is resolved against PROJECT_ROOT — the real skills/
    # tree must lint clean under --enforce (this also guards the CI gate).
    code = _run(monkeypatch, ["skills", "--enforce"])
    assert code == 0
    assert "enforce: clean" in capsys.readouterr().out
