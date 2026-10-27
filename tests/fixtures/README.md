# Test Fixtures — vostlit-research

These HTML files are **snapshots of pages from https://www.vostlit.info/** saved
solely for **offline testing of the parser** in this project. They must **not** be
redistributed or used for any purpose other than running this project's test suite.

## Provenance

- Source site: https://www.vostlit.info/  (Russian-language medieval historical sources library)
- Fetched: see `fixtures_manifest.json` (`fetched_at`, Europe/Moscow timezone)
- User-Agent used: `Mozilla/5.0 (compatible; vostlit-research-audit/0.1)`
- Politeness: 3-4 s sleep between requests; 15 distinct pages fetched in total.

## Encoding (IMPORTANT)

The site serves all HTML as **`text/html; charset=windows-1251`** (Cyrillic legacy
encoding). Fixtures are saved **as raw server bytes** (not re-encoded). When writing
tests, decode the bytes with Python's `'windows-1251'` codec before passing to
BeautifulSoup. Do **not** rely on BeautifulSoup's auto-detection — it sometimes
mis-detects.

Example:
```python
raw = pathlib.Path("tests/fixtures/home.html").read_bytes()
html = raw.decode("windows-1251")
soup = BeautifulSoup(html, "lxml")
```

## Files

See `fixtures_manifest.json` for the authoritative list: filename, source_url,
fetched_at, http_status, content_type, byte_size, sha256, description.

Files marked `.fragment.html` are **truncated** snapshots (the original page was
too large to keep in full). The truncation is noted in the file's HTML header
comment and in the manifest `description`. Do not parse a fragment as if it were
a complete page.

## Copyright

The underlying texts on vostlit.info are © their respective authors, translators,
and the site maintainers (Thietmar et al.), as declared in each page's `#dann`
block or footer. These fixture copies are made for the sole purpose of offline
parser testing under fair-use / research provisions and must not be redistributed.
