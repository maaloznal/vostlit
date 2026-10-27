"""Pluggable semantic search.

By default ``semantic_provider == "none"`` and :class:`NoopSemanticProvider`
returns an empty list — the rest of the search engine continues to work.

A real provider can be plugged in by:
  1. implementing the :class:`SemanticProvider` interface,
  2. registering it via :func:`register_provider`, and
  3. setting ``semantic_provider`` in config to its name.

No fake vectors are ever produced: when the provider is the no-op, semantic
search simply contributes zero results to the hybrid ranking.
"""

from __future__ import annotations

from typing import Any, Callable

from ..db import Database

_PROVIDERS: dict[str, Callable[[Database], "SemanticProvider"]] = {}


class SemanticProvider:
    name = "base"

    def search(self, query: str, filters: Any, *, limit: int = 50) -> list:
        raise NotImplementedError


class NoopSemanticProvider(SemanticProvider):
    name = "none"

    def search(self, query: str, filters: Any, *, limit: int = 50) -> list:
        return []


def register_provider(name: str, factory: Callable[[Database], SemanticProvider]) -> None:
    _PROVIDERS[name] = factory


def get_semantic_provider(db: Database) -> SemanticProvider:
    # config may set the provider name; default to "none"
    name = "none"
    try:
        from ..config import load_config
        name = (load_config().semantic_provider or "none").lower()
    except Exception:  # noqa: BLE001
        name = "none"
    factory = _PROVIDERS.get(name)
    if factory is None:
        return NoopSemanticProvider()
    try:
        return factory(db)
    except Exception:  # noqa: BLE001
        # a broken provider must never break the rest of search
        return NoopSemanticProvider()


# Self-register the no-op.
register_provider("none", lambda db: NoopSemanticProvider())
