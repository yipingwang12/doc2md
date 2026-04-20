# CLAUDE.md — doc2md

Local-first CLI pipeline converting PDFs and screenshot folders into chapter-split Markdown, with a built-in web e-book reader. PyMuPDF for digital PDFs, Surya OCR for scanned/screenshot sources, rule-based structure analysis with LLM fallback.

See [PRD.md](PRD.md) for full pipeline stages, data model, CLI reference, config schema, and academic paper pipeline.

## Architecture

```
src/doc2md/
├── ingest/          # rclone_sync, file_scanner (PDF + screenshot folder discovery)
├── extract/         # detect (digital vs scanned), pdf_extract (PyMuPDF), ocr_extract (Surya)
├── assembly/        # cleaner, footnotes, citations, merger, index_linker
├── ordering/        # dedup (hash→fuzzy→LLM), reorder, gap detection
├── analysis/        # segmenter, classifier (rule-based + font metadata), chapter_detector
└── output/          # markdown_writer (per-chapter .md + footnotes + bibliography)
```

## Pipeline stages (in order)

1. Ingest — rclone sync from Google Drive + local dir scan
2. Extract — detect digital vs scanned; PyMuPDF or Surya OCR
3. Clean — normalize ligatures, strip headers/footers/page numbers
4. Order — dedup, page-number detection, reorder, gap warnings
5. Classify — rule-based segmentation (heading/body/footnote/caption/reference/index)
6. Structure — chapter detection (rule-based, LLM fallback on ambiguity)
7. Assemble — link footnotes, extract bibliography, merge across page breaks
8. Output — per-chapter `.md` files

## Key design decisions

- LLM used **only as fallback** — rules cover the common case
- Libby spreads: landscape + uniform dimensions → auto-split at midpoint
- OCR cascade: PyMuPDF → Apple Vision → Surya (from PRD)

## Dev commands

```sh
doc2md sync            # pull from Google Drive
doc2md run             # full pipeline
doc2md status          # cache status
doc2md process <path>  # single file
doc2md link-index <vol> # link index entries to chapters
doc2md-reader          # launch desktop e-book reader (PyWebView)
```

## Desktop App

`src/doc2md/desktop.py` — PyWebView wrapper around the `reader/` web UI. Starts an embedded `http.server` on a free port and opens a native macOS window (WKWebView).

**Desktop .app bundle** (`~/Desktop/doc2md Reader.app`) — hand-crafted bundle (same pattern as Quiz.app): bash script launcher + `Info.plist` + custom icon. No py2app needed.

```
~/Desktop/doc2md Reader.app/
  Contents/MacOS/doc2md Reader   # bash: cd repo && exec .venv/bin/doc2md-reader
  Contents/Resources/doc2md-reader.icns
  Contents/Info.plist
```

- `assets/doc2md-reader.icns` — Pillow-generated icon (navy bg, document page with corner fold + teal arrow). Regenerate with `python scripts/make_icons.py` from the Projects root.
- `_desktop_build/setup.py` — isolated from `pyproject.toml` to avoid py2app 0.28 `install_requires` conflict; kept for py2app alias builds if needed
- `reader/vendor/` — bundled `markdown-it.min.js` + `markdown-it-footnote.min.js` for offline use (no CDN dependency)
