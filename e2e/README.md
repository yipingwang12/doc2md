# e2e — Playwright tests for the web reader

Run: `.venv/bin/pytest e2e/ -q` (not collected by default `pytest`; pyproject `testpaths=["tests"]`).

Serves a temp copy of `reader/` plus a fixture `library.json` + chapter markdown via `http.server` (same model as `src/doc2md/desktop.py`), drives headless Chromium via pytest-playwright.

Covers: HTML-escaped titles/metadata, per-book/per-chapter reading positions, reload resume, context-only citation popovers, TOC + page-turn clamping, graceful handling of the old localStorage prefs shape.

Known bug (test xfailed): reload restores book+chapter but not page — `init()`'s `applyTheme`/`applyFontSize` call `savePrefs` with `currentPage=0` before `openChapter` reads the saved position, clobbering it. Drop the xfail in `test_reload_resumes_position` once reader.js is fixed.
