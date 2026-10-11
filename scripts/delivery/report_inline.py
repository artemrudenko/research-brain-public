"""report_inline.py — the report-flavored inline markdown renderer.

One-function module so both `digest_report_html.py` and the tab-renderer
modules split out of it (`report_concepts.py`, `report_vault.py`, ...) can
import `inline` without a circular dependency on `digest_report_html` itself.
"""

from __future__ import annotations

from scripts.delivery.email_html import inline as _email_inline


def inline(text: str) -> str:
    """Inline markdown for the report: same escaping, no email inline styles.

    The report ships a real stylesheet, so links/code must stay bare elements
    the theme tokens own — the email path's hard-coded indigo/grey would break
    dark mode and fork the palette.
    """
    return _email_inline(text, inline_styles=False)
