"""Research engine: high-level tools the agent calls.

Each function returns plain data (dicts/lists) so it is trivial to serialise
for an MCP server, a CLI, or direct in-process use. None of these functions
ever returns fabricated data: if the corpus has nothing, they say so.
"""

from __future__ import annotations

from .api import ResearchEngine  # noqa: F401

__all__ = ["ResearchEngine"]
