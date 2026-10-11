"""Tests for deterministic OPML import preview and apply."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import import_opml as opml  # noqa: E402
from scripts import manage_sources as ms  # noqa: E402

EXAMPLE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "example_config"


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    # The ACTIVE config is the YAML twins (YAML-only since 0.8.0, CONVENTIONS
    # §2.3) plus the tag registry — the same trio a fresh install ships.
    d = tmp_path / "config"
    d.mkdir()
    for name in ("sources.yaml", "topics.yaml", "tags.yaml"):
        (d / name).write_text((EXAMPLE_CONFIG / name).read_text(encoding="utf-8"))
    return d


def _write_opml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "subscriptions.opml"
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Subscriptions</title></head>
  <body>
{body}
  </body>
</opml>
""",
        encoding="utf-8",
    )
    return path


def _basic_opml(tmp_path: Path) -> Path:
    return _write_opml(
        tmp_path,
        """
    <outline text="AI Agents">
      <outline text="Agent Blog" title="Agent Blog" type="rss" xmlUrl="https://agents.example.com/feed.xml" />
      <outline text="Atom Lab" type="atom" xmlUrl="https://atom.example.com/feed" />
    </outline>
    <outline text="Root Feed" type="rss" xmlUrl="https://root.example.com/rss" />
""",
    )


def _read_config_bytes(config_dir: Path) -> dict[str, bytes]:
    # Snapshot the files import writes through manage_sources: the active YAML
    # twins plus tags.yaml (add_topic seeds a domain key there).
    return {
        name: (config_dir / name).read_bytes()
        for name in ("sources.yaml", "topics.yaml", "tags.yaml")
    }


def _cli(config_dir: Path, *args: str) -> int:
    return opml.main([*args, "--config-dir", str(config_dir)])


def test_preview_is_read_only(config_dir: Path, tmp_path: Path) -> None:
    path = _basic_opml(tmp_path)
    before = _read_config_bytes(config_dir)

    entries = opml.parse_opml(path)
    preview = opml.build_preview(entries, config_dir)

    assert _read_config_bytes(config_dir) == before
    assert preview["counts"]["ready"] == 3
    assert preview["counts"]["selected"] == 3
    assert {item["status"] for item in preview["items"]} == {"ready"}
    assert all(isinstance(item["selected"], bool) for item in preview["items"])
    assert {item["resulting_topic"] for item in preview["items"]} == {
        "ai-agents",
        "imported",
    }


def test_apply_requires_confirmed_or_automatic(
    config_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _basic_opml(tmp_path)

    assert _cli(config_dir, "--apply", str(path)) == 2
    assert "confirmation" in capsys.readouterr().err.lower()
    assert not any(
        source.url == "https://agents.example.com/feed.xml"
        for category in ms.list_state(config_dir).categories
        for source in category.sources
    )

    assert _cli(config_dir, "--automatic", str(path), "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["added"] == 3


def test_reimport_is_byte_idempotent(config_dir: Path, tmp_path: Path) -> None:
    path = _basic_opml(tmp_path)
    preview = opml.build_preview(opml.parse_opml(path), config_dir)
    result = opml.apply_preview(preview, config_dir)
    assert result["counts"]["added"] == 3

    before = _read_config_bytes(config_dir)
    again = opml.build_preview(opml.parse_opml(path), config_dir)
    result_again = opml.apply_preview(again, config_dir)

    assert result_again["counts"]["added"] == 0
    assert _read_config_bytes(config_dir) == before


def test_root_feeds_use_imported_topic(config_dir: Path, tmp_path: Path) -> None:
    path = _write_opml(
        tmp_path,
        '<outline text="Root Feed" type="rss" xmlUrl="https://root.example.com/rss" />',
    )
    preview = opml.build_preview(opml.parse_opml(path), config_dir)

    assert preview["items"][0]["resulting_topic"] == "imported"
    assert preview["items"][0]["topic_label"] == "Imported"

    result = opml.apply_preview(preview, config_dir)
    assert result["counts"]["added"] == 1
    categories = {category.name: category for category in ms.list_state(config_dir).categories}
    assert categories["imported"].sources[0].url == "https://root.example.com/rss"


def test_folder_slug_collision_does_not_merge_topics(
    config_dir: Path, tmp_path: Path
) -> None:
    path = _write_opml(
        tmp_path,
        """
    <outline text="AI Agents">
      <outline text="One" type="rss" xmlUrl="https://one.example.com/feed.xml" />
    </outline>
    <outline text="AI--Agents">
      <outline text="Two" type="rss" xmlUrl="https://two.example.com/feed.xml" />
    </outline>
    <outline text="🚀🚀">
      <outline text="Emoji" type="rss" xmlUrl="https://emoji.example.com/feed.xml" />
    </outline>
""",
    )

    preview = opml.build_preview(opml.parse_opml(path), config_dir)
    topics = [item["resulting_topic"] for item in preview["items"]]

    assert topics[0] == "ai-agents"
    assert topics[1].startswith("ai-agents-")
    assert topics[1] != "ai-agents"
    assert topics[2].startswith("imported-")
    assert len(topics[2]) == len("imported-") + 8


def test_invalid_items_do_not_block_valid_feeds(config_dir: Path, tmp_path: Path) -> None:
    path = _write_opml(
        tmp_path,
        """
    <outline text="Valid" type="rss" xmlUrl="https://valid.example.com/feed.xml" />
    <outline text="FTP" type="rss" xmlUrl="ftp://bad.example.com/feed.xml" />
    <outline text="Missing" type="rss" />
    <outline text="Web" type="link" xmlUrl="https://web.example.com/" />
    <outline text="Duplicate" type="rss" xmlUrl="https://valid.example.com/feed.xml?utm_source=x" />
""",
    )

    preview = opml.build_preview(opml.parse_opml(path), config_dir)
    statuses = [item["status"] for item in preview["items"]]
    assert statuses == ["ready", "invalid", "invalid", "unsupported", "already_existing"]
    assert [item["selected"] for item in preview["items"]] == [
        True,
        False,
        False,
        False,
        False,
    ]

    result = opml.apply_preview(preview, config_dir)
    assert result["counts"]["added"] == 1


def test_default_selects_all_ready_items(config_dir: Path, tmp_path: Path) -> None:
    path = _write_opml(
        tmp_path,
        """
    <outline text="One" type="rss" xmlUrl="https://one.example.com/feed.xml" />
    <outline text="Bad" type="rss" xmlUrl="mailto:bad@example.com" />
    <outline text="Two" type="atom" xmlUrl="https://two.example.com/feed.xml" />
""",
    )

    preview = opml.build_preview(opml.parse_opml(path), config_dir)
    assert [(item["id"], item["status"], item["selected"]) for item in preview["items"]] == [
        ("feed-001", "ready", True),
        ("feed-002", "invalid", False),
        ("feed-003", "ready", True),
    ]


def test_select_is_ready_item_whitelist(config_dir: Path, tmp_path: Path) -> None:
    path = _basic_opml(tmp_path)
    preview = opml.build_preview(
        opml.parse_opml(path), config_dir, selected=["feed-001", "feed-003"]
    )

    assert [(item["id"], item["selected"]) for item in preview["items"]] == [
        ("feed-001", True),
        ("feed-002", False),
        ("feed-003", True),
    ]
    assert preview["counts"]["selected"] == 2


def test_invalid_selection_or_assignment_exits_2_without_writes(
    config_dir: Path, tmp_path: Path
) -> None:
    path = _write_opml(
        tmp_path,
        """
    <outline text="Ready" type="rss" xmlUrl="https://ready.example.com/feed.xml" />
    <outline text="Bad" type="rss" xmlUrl="ftp://bad.example.com/feed.xml" />
""",
    )
    before = _read_config_bytes(config_dir)

    cases = [
        ("--select", "feed-999"),
        ("--select", "nope"),
        ("--select", "feed-001,feed-001"),
        ("--assign", "feed-999=existing-topic"),
        ("--assign", "nope=existing-topic"),
        ("--assign", "feed-001=Bad Topic"),
        ("--assign", "feed-002=existing-topic"),
        ("--assign", "feed-001=existing-topic", "--assign", "feed-001=another"),
    ]

    for args in cases:
        assert _cli(config_dir, str(path), *args, "--apply", "--confirmed") == 2
        assert _read_config_bytes(config_dir) == before


def test_assignment_changes_preview_before_confirmation(
    config_dir: Path, tmp_path: Path
) -> None:
    ms.add_topic(config_dir, "existing-topic")
    path = _basic_opml(tmp_path)

    preview = opml.build_preview(
        opml.parse_opml(path), config_dir, assignments={"feed-003": "existing-topic"}
    )

    assert preview["items"][2]["id"] == "feed-003"
    assert preview["items"][2]["resulting_topic"] == "existing-topic"
    assert preview["items"][2]["assignment"] == "existing-topic"


def test_assignment_to_unselected_item_is_not_applied(
    config_dir: Path, tmp_path: Path
) -> None:
    path = _basic_opml(tmp_path)
    preview = opml.build_preview(
        opml.parse_opml(path),
        config_dir,
        selected=["feed-001"],
        assignments={"feed-003": "later-topic"},
    )

    assert preview["items"][2]["resulting_topic"] == "later-topic"
    assert preview["items"][2]["selected"] is False

    result = opml.apply_preview(preview, config_dir)
    assert result["counts"]["added"] == 1
    state = ms.list_state(config_dir)
    assert "later-topic" not in {topic.name for topic in state.topics}


def test_imported_source_values_are_exact(config_dir: Path, tmp_path: Path) -> None:
    path = _basic_opml(tmp_path)
    result = opml.apply_preview(opml.build_preview(opml.parse_opml(path), config_dir), config_dir)
    assert result["counts"]["added"] == 3

    state = ms.list_state(config_dir)
    imported = [
        source
        for category in state.categories
        for source in category.sources
        if source.url == "https://agents.example.com/feed.xml"
    ][0]
    assert imported.type == "rss"
    assert imported.tier == "medium"
    assert imported.priority == "medium"
    assert imported.filter_note == "Imported from OPML"
    assert imported.active is True


def test_rejects_malformed_xml_doctype_and_oversize(tmp_path: Path) -> None:
    malformed = tmp_path / "bad.opml"
    malformed.write_text("<opml><body>", encoding="utf-8")
    with pytest.raises(opml.OpmlError):
        opml.parse_opml(malformed)

    doctype = tmp_path / "doctype.opml"
    doctype.write_text("<!DOCTYPE opml><opml><body /></opml>", encoding="utf-8")
    with pytest.raises(opml.OpmlError):
        opml.parse_opml(doctype)

    oversize = tmp_path / "huge.opml"
    oversize.write_bytes(b" " * (10 * 1024 * 1024 + 1))
    with pytest.raises(opml.OpmlError):
        opml.parse_opml(oversize)


def test_cli_help_lists_supported_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        opml.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--select", "--assign", "--apply", "--confirmed", "--automatic", "--json"):
        assert flag in out
