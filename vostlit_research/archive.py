"""Content-addressed local archive for raw HTML snapshots.

Each fetched page is stored as a file whose path is derived from the sha256 of
its bytes, so identical content is stored once and re-fetching an unchanged
page is a no-op. The archive is append-only by hash; deletion is not exposed
by the public API (the master prompt forbids destructive operations without
explicit need).
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def _shard_path(root: Path, digest: str) -> Path:
    # sharded layout: <root>/ab/cdef.../<digest>.html  (2-level fan-out)
    return root / digest[:2] / digest[2:4] / f"{digest}.html"


def store(root: Path, data: bytes, suffix: str = ".html") -> tuple[str, Path]:
    """Store ``data`` under the archive ``root``; return (sha256_hex, rel_path).

    ``rel_path`` is relative to ``root`` (so it can be stored in the DB and
    resolved later against the same root). Idempotent: writing the same bytes
    twice writes the same file once.
    """
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    path = _shard_path(root, digest).with_suffix(suffix)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    rel = path.relative_to(root).as_posix()
    return digest, Path(rel)


def resolve(root: Path, rel_path: str | Path) -> Path:
    """Resolve a stored relative path against the archive root (safety-checked)."""
    p = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in p.parents and p != root_resolved:
        raise ValueError(f"archive path escapes root: {rel_path}")
    return p


def read_text(root: Path, rel_path: str | Path, encoding: str = "utf-8") -> str:
    return resolve(root, rel_path).read_text(encoding=encoding, errors="replace")


def read_bytes(root: Path, rel_path: str | Path) -> bytes:
    return resolve(root, rel_path).read_bytes()
