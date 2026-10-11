"""Author monitoring: the roster the user accepted, and what it resolves to.

`config/authors.yaml` (CONVENTIONS §2.4) is read here into `MonitoredAuthor`
records and resolved into `CollectionPlan`s. Nothing in this package decides
that a person is worth following — `scripts/source_report/authors.py` suggests,
the user accepts, and only then does an entry exist to load.
"""

from scripts.authors.model import CollectionPlan, MonitoredAuthor
from scripts.authors.plan import resolve_plans
from scripts.authors.store import AUTHORS_YAML, load_authors, parse_authors_yaml_text

__all__ = [
    "AUTHORS_YAML",
    "CollectionPlan",
    "MonitoredAuthor",
    "load_authors",
    "parse_authors_yaml_text",
    "resolve_plans",
]
