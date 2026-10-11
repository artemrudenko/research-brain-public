"""source_report — the collection-decision journal and (later) its report.

`scripts/source_insights.py` is the stable facade over this package, following
ADR 0021. Stage one is the journal itself (`events` + `model`); the metrics and
rendering modules land on top of the data it accumulates.
"""
