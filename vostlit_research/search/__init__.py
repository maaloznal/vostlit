"""Search engine: exact, full-text (FTS5), name-variant, fuzzy, context, hybrid.

Public entry point: :class:`SearchEngine`.

Every result carries a verifiable link back to a document + section, an
explanation of WHY it matched, and a confidence note. Semantic search is
pluggable via :mod:`vostlit_research.search.semantic` and is a no-op by
default — no fake vectors are ever produced.
"""

from __future__ import annotations

from .engine import SearchEngine, SearchResult, SearchFilters  # noqa: F401

__all__ = ["SearchEngine", "SearchResult", "SearchFilters"]
