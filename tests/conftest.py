"""
conftest.py — shared pytest fixtures for the research-brain test suite.

Ensures the project root is on sys.path so `scripts` is importable as a
package, and provides reusable sample-article / temp-config fixtures.
"""
import socket
import sys
from pathlib import Path

import pytest

# Make the project root importable (tests run from the project root, but be
# robust to being invoked from elsewhere).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a real outbound socket.

    The suite is fully offline (web calls are mocked), so a live `socket.connect`
    means a test is accidentally reaching the network — a correctness and
    flakiness hazard. We block at `connect`, which catches urllib/requests without
    touching in-process subprocess pipes or the AF_UNIX sockets some tools use.
    Loopback stays allowed so a test may spin up a local server if it needs one."""
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object, *args: object):
        host = address[0] if isinstance(address, tuple) else None
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"network access blocked in tests: connect to {address!r}")
        return real_connect(self, address, *args)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


# A pipeline article with every required frontmatter key (CONVENTIONS §5).
VALID_ARTICLE = """\
---
source: example-blog
url: https://example.com/post
title: A Sample Article
author: Jane Doe
date_published: 2026-01-01
collected: 2026-01-02
category: example-topic
tags: [sample, test]
---

# A Sample Article

Body text.
"""


@pytest.fixture
def project_root() -> Path:
    """Absolute path to the project root."""
    return PROJECT_ROOT


@pytest.fixture
def valid_article_text() -> str:
    """Raw markdown for a fully-valid pipeline article."""
    return VALID_ARTICLE


@pytest.fixture
def article_dir(tmp_path: Path) -> Path:
    """Empty temp directory standing in for pipeline/1-incoming/."""
    d = tmp_path / "incoming"
    d.mkdir()
    return d


@pytest.fixture
def write_article(article_dir: Path):
    """Factory: write a .md file into the temp article dir; return its path."""

    def _write(name: str, text: str) -> Path:
        path = article_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write
