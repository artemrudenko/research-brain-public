"""collection — internals for the stable scripts/collect.py facade.

The public command and compatibility import surface stay in ``scripts.collect``.
These modules split the deterministic headless collector by responsibility so
future changes can stay local without changing cron, skills, docs, or tests.
"""
