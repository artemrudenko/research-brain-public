"""scripts.search — optional, config-gated external web-search provider.

The default research-brain experience uses Claude's built-in WebSearch tool
*inside the agent* and needs nothing here. This package only matters for the
headless path (cron, no agent) and for future fact-check corroboration: when
`config/search.yaml` selects `provider: tavily` and a key is present, the
dispatcher (`search.py`) calls the Tavily adapter (`tavily.py`). Missing key or
`provider: none` -> soft skip (empty list + message), never an exception.
"""
