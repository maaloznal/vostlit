"""Collector: polite HTTP fetcher + HTML parser + discovery + crawl orchestration.

Import paths:

    from vostlit_research.collector import Crawler, parse_page
    from vostlit_research.collector.http import HttpClient
    from vostlit_research.collector.parser import parse_page, ParsedPage
"""

from __future__ import annotations

from .parser import parse_page, ParsedPage, Section, Link, ImageRef  # noqa: F401
from .http import HttpClient  # noqa: F401
from .discover import discover, REGIONS, ALPHA_LETTERS  # noqa: F401
from .crawl import Crawler  # noqa: F401

__all__ = ["parse_page", "ParsedPage", "Section", "Link", "ImageRef",
           "HttpClient", "discover", "REGIONS", "ALPHA_LETTERS", "Crawler"]
