"""Configuration for vostlit_research.

Configuration is loaded with the following priority (later wins):

    1. built-in defaults
    2. a TOML config file (path given via $VOSTLIT_CONFIG or the `--config`
       CLI flag, default ``config/config.toml`` relative to the project root)
    3. environment variables prefixed with ``VOSTLIT_``

No secrets are required for normal operation. If a real site integration
needs credentials, they must be supplied via environment variables only and
must never be committed.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.toml"


@dataclass
class Config:
    # --- source site -------------------------------------------------------
    base_url: str = "https://www.vostlit.info/"
    allowed_domains: tuple[str, ...] = ("www.vostlit.info", "vostlit.info")
    allowed_sections: tuple[str, ...] = (
        "/",  # homepage
        "/haupt-Dateien/",  # alphabetical author index
        "/Texts/",  # documents (texts, catalogs, collections)
        "/common/",  # site-wide indexes (itogi)
    )
    user_agent: str = "Mozilla/5.0 (compatible; vostlit-research/0.1; +local-research)"

    # --- storage -----------------------------------------------------------
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "vostlit.db")
    archive_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "archive")
    store_html: bool = True  # keep raw HTML snapshots in the archive

    # --- http politeness ---------------------------------------------------
    http_timeout: float = 30.0
    request_delay: float = 3.0  # seconds between requests to the live site
    max_retries: int = 3
    retry_backoff: float = 2.0
    retry_jitter: float = 1.0
    max_pages_per_run: int = 25  # safety cap; the collector never crawls unbounded

    # --- logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_file: Path | None = None

    # --- semantic search (optional, pluggable) -----------------------------
    # When semantic_provider is "none" (the default) the search engine simply
    # omits semantic results. No fake vectors are ever produced.
    semantic_provider: str = "none"
    semantic_model: str = ""
    semantic_index_path: Path | None = None

    # --- misc --------------------------------------------------------------
    # Page types that the collector will actually fetch & parse. Others are
    # discovered but skipped (recorded in the inventory with status "skipped").
    fetch_page_types: tuple[str, ...] = (
        "document_text",
        "document_excerpt",
        "notes_page",
        "image_gallery",
        "collection_index",
    )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["db_path"] = str(self.db_path)
        d["archive_dir"] = str(self.archive_dir)
        if self.log_file is not None:
            d["log_file"] = str(self.log_file)
        if self.semantic_index_path is not None:
            d["semantic_index_path"] = str(self.semantic_index_path)
        d["allowed_domains"] = list(self.allowed_domains)
        d["allowed_sections"] = list(self.allowed_sections)
        d["fetch_page_types"] = list(self.fetch_page_types)
        return d

    # --- paths -------------------------------------------------------------
    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # --- env override ------------------------------------------------------
    def apply_env(self) -> None:
        def get(name: str) -> str | None:
            return os.environ.get(f"VOSTLIT_{name}")

        if (v := get("DB_PATH")):
            self.db_path = Path(v)
        if (v := get("ARCHIVE_DIR")):
            self.archive_dir = Path(v)
        if (v := get("BASE_URL")):
            self.base_url = v
        if (v := get("USER_AGENT")):
            self.user_agent = v
        if (v := get("REQUEST_DELAY")):
            try:
                self.request_delay = float(v)
            except ValueError:
                pass
        if (v := get("MAX_PAGES_PER_RUN")):
            try:
                self.max_pages_per_run = int(v)
            except ValueError:
                pass
        if (v := get("LOG_LEVEL")):
            self.log_level = v
        if (v := get("STORE_HTML")):
            self.store_html = v.strip().lower() in ("1", "true", "yes", "on")
        if (v := get("SEMANTIC_PROVIDER")):
            self.semantic_provider = v


def _deep_update(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load a Config from defaults + optional TOML file + environment."""
    cfg = Config()
    p = Path(path) if path else Path(os.environ.get("VOSTLIT_CONFIG", DEFAULT_CONFIG_PATH))
    if p.exists():
        with p.open("rb") as fh:
            data = tomllib.load(fh)
        # The TOML may use the same flat keys, or a [vostlit] section.
        section = data.get("vostlit", data)
        for k, v in section.items():
            if hasattr(cfg, k):
                if k in ("db_path", "archive_dir", "log_file", "semantic_index_path"):
                    v = Path(v) if v else None
                if k in ("allowed_domains", "allowed_sections", "fetch_page_types"):
                    v = tuple(v)
                setattr(cfg, k, v)
    cfg.apply_env()
    return cfg
