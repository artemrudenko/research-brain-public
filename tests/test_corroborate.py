"""
test_corroborate.py — offline tests for deterministic corroboration (CONVENTIONS §16).

No network, no conftest changes. Covers registrable-domain extraction (www /
subdomain / co.uk), distinct-domain counting, same-domain collapse, near-dup
text collapse across domains, multi/single levels, and the reader trust line.
"""


from scripts import corroborate as c  # noqa: E402

# --------------------------------------------------------------------------- #
# registrable_domain
# --------------------------------------------------------------------------- #


def test_registrable_domain_plain() -> None:
    assert c.registrable_domain("https://nytimes.com/article") == "nytimes.com"


def test_registrable_domain_strips_www() -> None:
    assert c.registrable_domain("https://www.nytimes.com/a") == "nytimes.com"


def test_registrable_domain_collapses_subdomain() -> None:
    assert c.registrable_domain("https://blog.openai.com/post") == "openai.com"


def test_registrable_domain_multi_part_tld() -> None:
    # co.uk is a multi-part suffix → keep three labels.
    assert c.registrable_domain("https://www.bbc.co.uk/news") == "bbc.co.uk"


def test_registrable_domain_bare_host_no_scheme() -> None:
    assert c.registrable_domain("example.org/path") == "example.org"


def test_registrable_domain_ignores_port() -> None:
    assert c.registrable_domain("https://news.site.com:8080/x") == "site.com"


def test_registrable_domain_empty_for_garbage() -> None:
    assert c.registrable_domain("") == ""
    assert c.registrable_domain("not a url") == ""


# --------------------------------------------------------------------------- #
# independent_sources — distinct domains
# --------------------------------------------------------------------------- #


def test_independent_sources_distinct_domains() -> None:
    sources = [
        {"url": "https://nytimes.com/a"},
        {"url": "https://reuters.com/b"},
        {"url": "https://bbc.co.uk/c"},
    ]
    assert c.independent_sources(sources) == 3


def test_independent_sources_same_domain_counts_once() -> None:
    # Two articles on the same publisher (incl. www / subdomain) = one source.
    sources = [
        {"url": "https://www.nytimes.com/a"},
        {"url": "https://nytimes.com/b"},
        {"url": "https://blog.nytimes.com/c"},
    ]
    assert c.independent_sources(sources) == 1


def test_independent_sources_skips_empty_urls() -> None:
    sources = [
        {"url": "https://reuters.com/a"},
        {"url": ""},
        {"date": "2026-06-15"},  # no url key at all
    ]
    assert c.independent_sources(sources) == 1


def test_independent_sources_empty_list() -> None:
    assert c.independent_sources([]) == 0


# --------------------------------------------------------------------------- #
# independent_sources — near-dup text collapse across domains
# --------------------------------------------------------------------------- #


def test_near_dup_texts_across_two_domains_collapse_to_one() -> None:
    # Same wire story republished on two distinct domains → 1 independent source.
    story = (
        "The central bank raised interest rates by half a point today, "
        "citing persistent inflation pressures across the economy."
    )
    sources = [
        {"url": "https://reuters.com/story"},
        {"url": "https://apnews.com/story"},
    ]
    texts = {
        "https://reuters.com/story": story,
        "https://apnews.com/story": story,  # identical reprint
    }
    # Without texts: two distinct domains → 2.
    assert c.independent_sources(sources) == 2
    # With texts collapsing the reprint: 1.
    assert c.independent_sources(sources, texts=texts) == 1


def test_distinct_stories_across_domains_stay_independent() -> None:
    sources = [
        {"url": "https://reuters.com/a"},
        {"url": "https://apnews.com/b"},
    ]
    texts = {
        "https://reuters.com/a": "Quarterly earnings beat analyst expectations.",
        "https://apnews.com/b": "A volcano erupted on a remote Pacific island.",
    }
    assert c.independent_sources(sources, texts=texts) == 2


# --------------------------------------------------------------------------- #
# corroboration level + trust_line
# --------------------------------------------------------------------------- #


def test_corroboration_level_multi() -> None:
    sources = [{"url": "https://a.com/x"}, {"url": "https://b.com/y"}]
    corr = c.corroboration(sources)
    # No texts → distinct domains only, collapse did NOT run (BUG C1).
    assert corr == {"independent": 2, "level": "multi", "collapsed": False}


def test_corroboration_level_single() -> None:
    sources = [{"url": "https://a.com/x"}, {"url": "https://a.com/y"}]
    corr = c.corroboration(sources)
    assert corr == {"independent": 1, "level": "single", "collapsed": False}


def test_corroboration_level_none() -> None:
    assert c.corroboration([]) == {
        "independent": 0, "level": "none", "collapsed": False,
    }


def test_trust_line_multi_collapsed_reports_publisher_diversity() -> None:
    # Text deduplication does not establish independent support for a claim.
    line = c.trust_line({"independent": 3, "level": "multi", "collapsed": True})
    assert line == "🔵 3 retained publisher domains — check the claim"


def test_distinct_texts_do_not_establish_independent_claim_confirmation() -> None:
    # These original synthetic passages could repeat one upstream announcement
    # despite low lexical overlap. The helper never inspects that dependency.
    sources = [{"url": "https://example.com/a"}, {"url": "https://example.org/b"}]
    texts = {
        "https://example.com/a": "The fictional studio announced a violet interface.",
        "https://example.org/b": "A new lavender design is described in the maker's release.",
    }
    corr = c.corroboration(sources, texts=texts)
    assert corr["independent"] == 2
    for language in ("en", "ru"):
        line = c.trust_line(corr, language=language)
        assert "🟢" not in line
        assert "Confirmed" not in line
        assert "independent" not in line
        assert "Подтверждено" not in line
        assert "независим" not in line


def test_trust_line_multi_uncollapsed_is_honest() -> None:
    # Distinct domains but same-story syndication not ruled out → no false claim.
    line = c.trust_line({"independent": 3, "level": "multi", "collapsed": False})
    assert line == "🔵 3 retained publisher domains — check the claim"


def test_trust_line_single() -> None:
    line = c.trust_line({"independent": 1, "level": "single"})
    assert line == "🟡 One retained publisher domain — check the claim"


def test_trust_line_empty_when_no_sources() -> None:
    assert c.trust_line({"independent": 0, "level": "none"}) == ""


# --------------------------------------------------------------------------- #
# Regression: registrable_domain hardening (C7)
# --------------------------------------------------------------------------- #


def test_c7_ipv4_is_its_own_domain() -> None:
    # An IPv4 literal must not be truncated to its last two octets ("0.1").
    assert c.registrable_domain("https://192.168.0.1/x") == "192.168.0.1"
    assert c.registrable_domain("https://8.8.8.8/y") == "8.8.8.8"


def test_c7_shared_hosting_subdomains_stay_distinct() -> None:
    # Distinct Substack/Medium/etc. authors are distinct publishers, not one.
    assert c.registrable_domain("https://alice.substack.com/p") == "alice.substack.com"
    assert c.registrable_domain("https://bob.substack.com/p") == "bob.substack.com"
    assert c.registrable_domain("https://x.medium.com/p") == "x.medium.com"
    assert c.registrable_domain("https://repo.github.io/page") == "repo.github.io"
    two = c.independent_sources(
        [{"url": "https://alice.substack.com/p"}, {"url": "https://bob.substack.com/q"}]
    )
    assert two == 2  # two independent Substack authors


def test_c7_extended_cctlds_keep_three_labels() -> None:
    assert c.registrable_domain("https://news.bbc.co.kr/x") == "bbc.co.kr"
    assert c.registrable_domain("https://shop.store.com.mx/y") == "store.com.mx"


# --------------------------------------------------------------------------- #
# Search-enriched corroboration (CONVENTIONS §15 wiring, §16 honesty)
# --------------------------------------------------------------------------- #


def test_search_enrich_upgrades_single_to_multi() -> None:
    # One existing source + two NEW independent domains found by search → multi.
    sources = [{"url": "https://techcrunch.com/story"}]

    def fake_search(query: str) -> list[dict]:
        return [
            {"title": "A", "url": "https://reuters.com/a"},
            {"title": "B", "url": "https://bbc.co.uk/b"},
        ]

    corr, discovered = c.corroborate_with_search(
        "ASML EUV China", sources, search_fn=fake_search
    )
    assert corr["level"] == "multi"
    assert corr["independent"] == 3
    assert corr["collapsed"] is False  # no texts → honest 🔵, never 🟢
    assert c.trust_line(corr).startswith("🔵")
    assert {d["url"] for d in discovered} == {
        "https://reuters.com/a",
        "https://bbc.co.uk/b",
    }


def test_search_enrich_skips_domains_already_present() -> None:
    # A hit on a domain already in `sources` must not inflate the count.
    sources = [{"url": "https://techcrunch.com/story"}]

    def fake_search(query: str) -> list[dict]:
        return [{"title": "dup", "url": "https://techcrunch.com/another"}]

    corr, discovered = c.corroborate_with_search("x", sources, search_fn=fake_search)
    assert corr["level"] == "single"
    assert discovered == []


def test_search_enrich_soft_skips_on_sentinel() -> None:
    # claude-websearch returns a sentinel note headlessly (kind == "note") — it is
    # not a real hit, so corroboration is unchanged.
    sources = [{"url": "https://techcrunch.com/story"}]

    def sentinel_search(query: str) -> list[dict]:
        return [{"kind": "note", "title": "use the in-agent WebSearch tool", "url": ""}]

    corr, discovered = c.corroborate_with_search("x", sources, search_fn=sentinel_search)
    assert corr["level"] == "single"
    assert discovered == []


def test_search_enrich_never_raises_on_search_error(capsys) -> None:
    sources = [{"url": "https://techcrunch.com/story"}]

    def boom(query: str) -> list[dict]:
        raise RuntimeError("network down")

    corr, discovered = c.corroborate_with_search("x", sources, search_fn=boom)
    assert corr["level"] == "single"  # falls back to base, no raise
    assert discovered == []
    # The soft-skip must leave a stderr breadcrumb (not silently swallow the error).
    err = capsys.readouterr().err
    assert "network down" in err


def test_search_enrich_caps_new_sources() -> None:
    sources: list[dict] = []

    def many(query: str) -> list[dict]:
        return [{"title": str(i), "url": f"https://site{i}.com/x"} for i in range(10)]

    _corr, discovered = c.corroborate_with_search(
        "x", sources, search_fn=many, max_new=3
    )
    assert len(discovered) == 3


# --------------------------------------------------------------------------- #
# Bare-string source entry path (_source_url accepts a string, not just a dict)
# --------------------------------------------------------------------------- #


def test_independent_sources_accepts_bare_string_entries() -> None:
    # A `sources:` entry may be a bare URL string rather than a {"url": ...} dict;
    # _source_url must read it, so two distinct bare-string domains count as 2.
    assert c.independent_sources(["https://a.example", "https://b.example"]) == 2
    # Two bare strings on the same publisher collapse to one independent source.
    assert c.independent_sources(["https://a.example/1", "https://a.example/2"]) == 1


# --------------------------------------------------------------------------- #
# CLI (_main): `enrich` prints the trust line and exits 0
# --------------------------------------------------------------------------- #


def test_main_enrich_prints_trust_line_and_exits_zero(monkeypatch, capsys) -> None:
    # The lazy default `from scripts.search.search import web_search` (when no
    # search_fn is passed) must resolve to our stub. Patch it at its definition
    # module so the late import picks it up; the stub returns no new domains so the
    # single --source stays single-source and a 🟡 trust line is printed.
    import scripts.search.search as search_mod

    monkeypatch.setattr(search_mod, "web_search", lambda query: [], raising=True)

    rc = c._main(["enrich", "the claim", "--source", "https://a.example"])
    out = capsys.readouterr().out

    assert rc == 0
    # One source -> the single-source trust line is printed (not "(no sources)").
    assert "One retained publisher domain" in out
