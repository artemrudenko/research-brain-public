"""
test_frontmatter.py — offline tests for the pipeline frontmatter validator.

Validates the behavior contract from docs/CONVENTIONS.md §5: an article passes
only when it opens with `---` and declares every required key. Uses tmp files;
touches no real pipeline content.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_validator():
    """Load the hyphen-named validator module via importlib."""
    path = _PROJECT_ROOT / "scripts" / "validate-pipeline-frontmatter.py"
    spec = importlib.util.spec_from_file_location("validate_pipeline_frontmatter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def test_valid_article_passes(write_article, valid_article_text, article_dir):
    write_article("good.md", valid_article_text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    assert problems == {}


def test_article_with_schema_version_stamp_passes(
    write_article, valid_article_text, article_dir
):
    # The frontmatter schema-version stamp collect.py/inbox.py now emit must not be
    # rejected by the strict pipeline validator (it checks required keys, not an
    # exact key set) — otherwise every freshly collected article would fail.
    stamped = valid_article_text.replace("---\n", "---\nschema_version: 1\n", 1)
    write_article("stamped.md", stamped)
    total, problems = validator.scan(article_dir)
    assert total == 1
    assert problems == {}


def test_missing_frontmatter_fails(write_article, article_dir):
    write_article("no-fm.md", "# Just a heading\n\nNo frontmatter at all.\n")
    total, problems = validator.scan(article_dir)
    assert total == 1
    assert len(problems) == 1
    (reason,) = problems.values()
    assert "missing YAML frontmatter block" in reason


def test_missing_required_key_fails(write_article, article_dir):
    # Drop the `author` key from an otherwise-valid block.
    text = """\
---
source: example-blog
url: https://example.com/post
title: A Sample Article
date_published: 2026-01-01
collected: 2026-01-02
category: example-topic
tags: [sample]
---

Body.
"""
    write_article("missing-key.md", text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    (reason,) = problems.values()
    # Strict validator reports missing AND blank keys under one message.
    assert "missing or empty required keys" in reason
    assert "author" in reason


def test_blank_line_before_fence_fails(write_article, valid_article_text, article_dir):
    # The fence must be the FIRST line (byte 0). A blank line before `---`
    # means the article does not "begin with `---`" per CONVENTIONS §5 ->
    # reported as missing frontmatter (was previously, leniently, passing).
    write_article("leading-blank.md", "\n" + valid_article_text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    (reason,) = problems.values()
    assert "missing YAML frontmatter block" in reason


def test_bom_then_fence_passes(write_article, valid_article_text, article_dir):
    # A leading UTF-8 BOM before `---` on line 1 is tolerated (editors emit it);
    # the fence is still effectively the first line.
    write_article("bom.md", "﻿" + valid_article_text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    assert problems == {}


def test_unclosed_frontmatter_fails(write_article, article_dir):
    # Opening `---` but never closed -> treated as malformed (no block).
    write_article("unclosed.md", "---\nsource: x\ntitle: y\n\nbody with no closing fence\n")
    total, problems = validator.scan(article_dir)
    assert total == 1
    (reason,) = problems.values()
    assert "missing YAML frontmatter block" in reason


def test_index_md_is_ignored(write_article, valid_article_text, article_dir):
    write_article("index.md", "no frontmatter here\n")
    write_article("good.md", valid_article_text)
    total, problems = validator.scan(article_dir)
    assert total == 1  # index.md skipped
    assert problems == {}


def test_missing_target_dir_is_empty(tmp_path):
    total, problems = validator.scan(tmp_path / "does-not-exist")
    assert total == 0
    assert problems == {}


def test_strict_exit_code(write_article, article_dir, monkeypatch):
    """--strict + a bad file exits 2; clean run exits 0."""
    write_article("bad.md", "no frontmatter\n")
    monkeypatch.setattr(
        sys, "argv", ["prog", str(article_dir), "--strict"]
    )
    with pytest.raises(SystemExit) as exc:
        validator.main()
    assert exc.value.code == 2


# --- Strict-value rules (parsed with yaml.safe_load) -----------------------


def test_blank_required_value_fails(write_article, article_dir):
    # Every required key is PRESENT but `author` is blank -> reject.
    text = """\
---
source: example-blog
url: https://example.com/post
title: A Sample Article
author:
date_published: 2026-01-01
collected: 2026-01-02
category: example-topic
tags: [sample]
---

Body.
"""
    write_article("blank-value.md", text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    (reason,) = problems.values()
    assert "empty" in reason.lower() or "missing" in reason.lower()
    assert "author" in reason


def test_malformed_yaml_reported_not_crashed(write_article, article_dir):
    # Unterminated flow list -> yaml.safe_load raises; must be reported,
    # not surface as a traceback.
    text = """\
---
source: example-blog
url: https://example.com/post
title: A Sample Article
author: Jane Doe
date_published: 2026-01-01
collected: 2026-01-02
category: example-topic
tags: [a, b
---

Body.
"""
    write_article("malformed.md", text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    (reason,) = problems.values()
    assert "invalid" in reason.lower() or "yaml" in reason.lower()


def test_non_list_tags_fails(write_article, article_dir):
    # `tags` is a bare scalar instead of a list -> reject.
    text = """\
---
source: example-blog
url: https://example.com/post
title: A Sample Article
author: Jane Doe
date_published: 2026-01-01
collected: 2026-01-02
category: example-topic
tags: sample
---

Body.
"""
    write_article("scalar-tags.md", text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    (reason,) = problems.values()
    assert "tags" in reason


def test_bad_url_fails(write_article, article_dir):
    # `url` is not an http(s) URL -> reject.
    text = """\
---
source: example-blog
url: not-a-url
title: A Sample Article
author: Jane Doe
date_published: 2026-01-01
collected: 2026-01-02
category: example-topic
tags: [sample]
---

Body.
"""
    write_article("bad-url.md", text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    (reason,) = problems.values()
    assert "url" in reason


def test_bad_date_fails(write_article, article_dir):
    # `date_published` is not a valid YYYY-MM-DD date -> reject.
    text = """\
---
source: example-blog
url: https://example.com/post
title: A Sample Article
author: Jane Doe
date_published: not-a-date
collected: 2026-01-02
category: example-topic
tags: [sample]
---

Body.
"""
    write_article("bad-date.md", text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    (reason,) = problems.values()
    assert "date_published" in reason


def test_fully_valid_article_still_passes(write_article, valid_article_text, article_dir):
    # The strict rules must not reject a well-formed real article.
    write_article("good.md", valid_article_text)
    total, problems = validator.scan(article_dir)
    assert total == 1
    assert problems == {}
