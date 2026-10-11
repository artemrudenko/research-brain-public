"""
test_normalize_url.py — canonical dedup-key tests for scripts/normalize_url.py (R8).

Covers the cases that previously slipped past the query-strip-only dedup:
http vs https, www/m prefixes, trailing slash, #fragment, query strip, and the
end-to-end guarantee that two real-world variants of one article share a key.
"""
from scripts.normalize_url import normalize


def test_http_and_https_dedup_to_same_key() -> None:
    assert normalize("http://example.com/post") == normalize("https://example.com/post")


def test_www_prefix_stripped() -> None:
    assert normalize("https://www.example.com/post") == normalize("https://example.com/post")


def test_m_prefix_stripped() -> None:
    assert normalize("https://m.example.com/post") == normalize("https://example.com/post")


def test_trailing_slash_dropped() -> None:
    assert normalize("https://example.com/post/") == normalize("https://example.com/post")


def test_fragment_dropped() -> None:
    assert normalize("https://example.com/post#section") == normalize("https://example.com/post")


def test_query_stripped() -> None:
    assert normalize("https://example.com/post?utm_source=x&ref=y") == normalize(
        "https://example.com/post"
    )


def test_host_lowercased() -> None:
    assert normalize("https://Example.COM/post") == normalize("https://example.com/post")


def test_root_path_preserved() -> None:
    # A bare domain (root path) must not become an empty/invalid key.
    assert normalize("https://example.com/") == normalize("https://example.com")
    assert normalize("https://example.com").endswith("example.com")


def test_scheme_relative_url_gets_https() -> None:
    # URL without a scheme should still parse host/path correctly.
    assert normalize("example.com/post") == normalize("https://example.com/post")


def test_two_variants_of_same_article_map_to_one_key() -> None:
    # The combined, real-world case: all transforms at once must collapse.
    a = "https://www.Example.com/Post/?utm=x#sec"
    b = "http://example.com/Post"
    assert normalize(a) == normalize(b)


def test_distinct_articles_keep_distinct_keys() -> None:
    # Sanity: normalization must not over-collapse genuinely different URLs.
    assert normalize("https://example.com/post-a") != normalize("https://example.com/post-b")


# --------------------------------------------------------------------------- #
# Regression: URL normalization hardening (M3)
# --------------------------------------------------------------------------- #


def test_m3_default_ports_collapse():
    from scripts.normalize_url import normalize
    assert normalize("https://ex.com:443/a") == normalize("https://ex.com/a")
    assert normalize("http://ex.com:80/a") == normalize("https://ex.com/a")


def test_m3_non_default_port_preserved():
    # A non-default port identifies a distinct endpoint and must survive in the
    # normalized key, so `:8443` does not collapse into the default-port variant.
    assert normalize("https://h:8443/p") == "https://h:8443/p"
    assert normalize("https://h:8443/p") != normalize("https://h/p")


def test_m3_default_port_forced_https_drops_port():
    # http://h:80 is forced to https with no port (80 is the http default, treated
    # as the scheme default to drop).
    assert normalize("http://h:80/p") == normalize("https://h/p")
    assert normalize("https://h:443/p") == normalize("https://h/p")


def test_m3_ipv6_literal_without_port_roundtrips():
    # A bracketed IPv6 literal host must keep its brackets in the output netloc.
    assert normalize("https://[2001:db8::1]/p") == "https://[2001:db8::1]/p"


def test_m3_ipv6_literal_with_port_roundtrips():
    # Brackets AND a non-default port both survive for an IPv6 literal host.
    assert normalize("https://[2001:db8::1]:8080/p") == "https://[2001:db8::1]:8080/p"


def test_m3_ipv6_literal_default_port_dropped():
    # The default port drops, but the IPv6 brackets remain intact.
    assert normalize("https://[2001:db8::1]:443/p") == normalize("https://[2001:db8::1]/p")
    assert normalize("https://[2001:db8::1]:443/p") == "https://[2001:db8::1]/p"


def test_m3_userinfo_is_dropped():
    from scripts.normalize_url import normalize
    assert normalize("https://user:pass@ex.com/a") == normalize("https://ex.com/a")


def test_m3_non_http_scheme_passes_through():
    from scripts.normalize_url import normalize
    assert normalize("mailto:foo@bar.com") == "mailto:foo@bar.com"


# --------------------------------------------------------------------------- #
# Regression: meaningful query params are kept, only tracking is stripped (M2)
# --------------------------------------------------------------------------- #


def test_m2_distinct_youtube_videos_keep_distinct_keys() -> None:
    # Two YouTube videos differ only by `v=` — they are different articles and
    # must NOT collapse to one dedup key (else all but the first are never collected).
    a = "https://youtube.com/watch?v=AAA"
    b = "https://youtube.com/watch?v=BBB"
    assert normalize(a) != normalize(b)


def test_m2_tracking_param_stripped_but_content_param_kept() -> None:
    # utm_source is tracking → dropped; v is meaningful → kept. So a URL with the
    # tracking param and one without it (but same `v`) share a key.
    assert normalize("https://youtube.com/watch?utm_source=x&v=AAA") == normalize(
        "https://youtube.com/watch?v=AAA"
    )


def test_m2_query_param_order_normalizes_to_same_key() -> None:
    # Param order is not significant — re-serialized sorted, so both map to one key.
    assert normalize("https://ex.com/p?a=1&b=2") == normalize("https://ex.com/p?b=2&a=1")


def test_m2_distinct_wordpress_query_articles_keep_distinct_keys() -> None:
    # WordPress `?p=` / `?id=` / `?page=` identify distinct content.
    assert normalize("https://blog.com/?p=123") != normalize("https://blog.com/?p=456")
    assert normalize("https://blog.com/list?page=2") != normalize("https://blog.com/list?page=3")


def test_m2_known_tracking_params_all_stripped() -> None:
    # The full tracking set (utm_*, fbclid, gclid, mc_eid, igshid, ref) drops away.
    tracked = (
        "https://ex.com/p?utm_source=a&utm_medium=b&utm_campaign=c&fbclid=d"
        "&gclid=e&mc_eid=f&igshid=g&ref=h"
    )
    assert normalize(tracked) == normalize("https://ex.com/p")


# ── source (feed) URLs, not just article URLs ─────────────────────────────────
#
# The same normalizer is the identity key for a monitored SOURCE, not only for
# article dedup. That reuse is only safe because the query string is filtered
# rather than dropped: a search-driven feed carries its whole meaning in the
# query, so two topic feeds from one host must not collapse into one source.
# These pin that property directly, since nothing else in the suite states it
# from the source side.


def test_search_feeds_differing_only_by_query_stay_distinct_sources() -> None:
    # Google News-style search feeds: same path, different topic. Collapsing
    # these would silently merge two monitored sources into one.
    assert normalize("https://news.google.com/rss/search?q=ai") != normalize(
        "https://news.google.com/rss/search?q=robotics"
    )


def test_feed_query_parameters_survive_normalization() -> None:
    # The params that select WHAT a feed carries are content-bearing and kept.
    assert (
        normalize("https://example.com/feed?category=ml&format=atom")
        == "https://example.com/feed?category=ml&format=atom"
    )


def test_tracking_params_are_still_stripped_from_feed_urls() -> None:
    # Filtering, not preserving wholesale: a campaign-tagged feed link and the
    # plain one are the same source.
    assert normalize("https://example.com/feed.xml?utm_source=newsletter") == normalize(
        "https://example.com/feed.xml"
    )


def test_ref_param_is_treated_as_tracking_a_known_trade_off() -> None:
    """`ref` is stripped — right for `?ref=hn`, wrong for a git-forge branch feed.

    Documented rather than fixed: `ref` is overwhelmingly a referrer tag in the
    wild (`?ref=hn`, `?ref=twitter`), and article dedup depends on those variants
    collapsing. A host that uses `ref` semantically (a forge feed pinned to a
    branch) would fold onto its default-branch feed. If that ever bites, the fix
    is a per-host exception, NOT dropping `ref` from the tracking set — that
    would regress dedup for every referrer-tagged article.
    """
    assert normalize("https://forge.example/repo/commits?ref=main") == normalize(
        "https://forge.example/repo/commits?ref=develop"
    )
