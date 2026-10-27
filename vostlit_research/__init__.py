"""
vostlit_research — a local, reproducible research system for the historical
sources published at https://www.vostlit.info/.

The package is organised in five components (see docs/ARCHITECTURE.md):

    collector/  — polite HTTP fetcher + HTML parsers per verified page type
    archive/    — content-addressed local store of raw HTML snapshots
    search/     — FTS5 full-text + exact + name-variant + fuzzy + context search
    research/   — high-level research tools (get_document, find_mentions, ...)
    (cli)       — `python -m vostlit_research ...` entry point

Design principles (see SKILL.md and docs/):
  * Every historical claim must keep a verifiable link to a source fragment.
  * Original spellings are never destroyed; normalisation is a separate view.
  * The system works fully offline once a corpus is imported; the live site is
    only contacted on explicit collector commands.
  * Minimal dependencies: stdlib sqlite3 (with FTS5) + httpx + beautifulsoup4
    + pydantic. No external DB, no vector store, no always-on cloud API.
"""

from __future__ import annotations

__version__ = "0.4.0"

# Public, stable import surface (kept tiny on purpose).
from .config import Config, load_config  # noqa: E402,F401
from .db import Database, connect  # noqa: E402,F401

__all__ = ["Config", "load_config", "Database", "connect", "__version__"]
