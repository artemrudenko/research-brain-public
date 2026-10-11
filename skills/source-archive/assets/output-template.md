---
title: "{Original article title}"
type: source
status: active
created: {YYYY-MM-DD}
last_updated: {YYYY-MM-DD}
topic_tags: []

url: "https://{host}/{path}"
host: {host}
tier: T1                                # T1 / T2 / T3 / unregistered
author: ""                              # optional, extracted from <meta>
published: ""                           # optional, extracted from <meta>
fetched_at: {YYYY-MM-DD}
fetched_via: webfetch                   # webfetch / browser / manual
access: webfetch                        # webfetch / browser-required / auth-required / manual

hash: sha256:{hex}                      # for drift detection

needed_for: ""                          # path to the research brief if one is active

generated_by: source-archive

# NOTE (MODE=instruction-stripping): the audit fields below are NOT written into
# THIS original archive — `sanitize_incoming.sanitize_file()` writes them into the
# sanitized COMPANION at {{ARCHIVE_ROOT}}/sanitized/{filename}.md. Listed here only
# so the companion shape is visible alongside the archive it shadows:
#   instruction_stripped: true
#   stripped_at: {ISO-8601}
#   source_hash: {sha256 of this original source file}
#   sanitized_hash: {sha256 of the whole companion, self-field neutralized}
#   stripped_classes: [S1, S5, S9]          # STRIPPED classes only (flagged-not-stripped omitted)
#   stripping_severity: critical | medium | clean
---

# {Original title}

{verbatim content extracted from the web page}

---

**Source:** {URL}
**Fetched:** {YYYY-MM-DD} via {WebFetch | browser-fetch | manual}
**Archive path:** {{ARCHIVE_ROOT}}/{YYYY-MM-DD}_{host}_{slug}.md
