"""pytest config: path setup + shared fixtures."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from vostlit_research.db import Database  # noqa: E402
from vostlit_research.config import Config  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture()
def tmp_db(tmp_path) -> Database:
    db = Database(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture()
def cfg(tmp_path) -> Config:
    c = Config()
    c.db_path = tmp_path / "test.db"
    c.archive_dir = tmp_path / "archive"
    c.request_delay = 0.0  # tests must not sleep
    c.max_pages_per_run = 1000
    c.ensure_dirs()
    return c


@pytest.fixture()
def fixture_bytes():
    def _load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()
    return _load


@pytest.fixture()
def fixture_url():
    manifest_path = FIXTURES / "fixtures_manifest.json"
    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapping = {f["filename"]: f["source_url"] for f in manifest["fixtures"]}
    return mapping
