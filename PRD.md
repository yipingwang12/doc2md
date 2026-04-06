# doc2md — Product Requirements Document

## Problem

Academic PDFs and book screenshots (e.g. from Libby/library apps) are trapped in opaque formats. Extracting structured, readable Markdown—with chapters, footnotes, citations, and captions intact—requires manual effort that doesn't scale across a personal library.

## Solution

`doc2md` is a local-first CLI pipeline that converts PDFs and screenshot folders into clean, chapter-split Markdown, plus a built-in web-based e-book reader. Uses PyMuPDF for digital PDFs, Surya OCR for scanned/screenshot sources, and rule-based structural analysis (LLM fallback for edge cases only).

## Input Sources

- **Digital PDFs**: text-layer extraction via PyMuPDF
- **Scanned PDFs**: auto-detected when text layer is missing/gibberish; pages rendered to images then OCR'd via Surya
- **Screenshot folders**: directories of page images (PNG/JPG/TIFF/BMP/WebP), sorted by filename
- **Libby spreads**: two-page spread screenshots auto-detected (landscape, uniform dimensions); split at midpoint, batched OCR, image-only pages skipped
- **Google Drive sync**: rclone pulls screenshots from a configurable remote (default: `gdrive:Books/Libby`)
- **Local directories**: configurable list of local paths to scan (default: `~/Papers`, `~/Books`)

## Pipeline Stages

| # | Stage | Module | Description |
|---|-------|--------|-------------|
| 1 | **Ingest** | `ingest/rclone_sync`, `ingest/file_scanner` | Sync from Google Drive; discover PDFs and screenshot folders in local dirs |
| 2 | **Extract** | `extract/detect`, `extract/pdf_extract`, `extract/ocr_extract` | Auto-detect digital vs scanned PDF; extract text + block dicts via PyMuPDF or Surya OCR |
| 3 | **Clean** | `assembly/cleaner` | Normalize ligatures; strip repeated headers/footers, page numbers, and URL boilerplate |
| 4 | **Order** | `ordering/dedup`, `ordering/reorder` | Deduplicate pages (hash → fuzzy → LLM fallback); detect page numbers via LLM; reorder; warn on gaps (screenshots only) |
| 5 | **Classify** | `analysis/segmenter`, `analysis/classifier` | Rule-based segmentation using PyMuPDF block structure and font metadata (size, name); falls back to raw text heuristics for OCR pages. Splits merged footnote blocks at superscript boundaries |
| 6 | **Structure** | `analysis/chapter_detector` | Rule-based chapter detection from heading levels; LLM fallback only when rules are ambiguous. Merges consecutive heading-only blocks into combined titles |
| 7 | **Assemble** | `assembly/footnotes`, `assembly/citations`, `assembly/merger` | Link footnotes (merging orphan continuations); extract bibliography; then merge body blocks across page breaks with hyphenation fix and sentence joining |
| 8 | **Output** | `output/markdown_writer` | Render each chapter to a separate `.md` file with footnotes section and numbered bibliography |

## Data Model

- **Page**: source path, raw text, extraction method, page number, content hash
- **TextBlock**: classified text unit (heading/body/footnote/caption/reference/index) with heading level and footnote ID
- **Chapter**: title, heading level, list of blocks, footnote map, bibliography list
- **Document**: source name, pages, chapters, metadata

## CLI Interface

```
doc2md [--config PATH] <command>

Commands:
  sync      Sync screenshots from Google Drive via rclone
  process   Process a single PDF or screenshot folder
              --output-dir PATH   Override output directory
              --force             Ignore cache, reprocess
              --model NAME        Override LLM model
  run       Full pipeline: sync + discover + process all
              --force
  status    Show cache status (files and completed stages)
  clean     Clear cache for reprocessing
```

## Configuration (`config.toml`)

| Section | Key | Default | Purpose |
|---------|-----|---------|---------|
| `paths` | `google_drive_remote` | `gdrive:Books/Libby` | rclone remote path |
| `paths` | `local_pdf_dirs` | `["~/Papers", "~/Books"]` | directories to scan |
| `paths` | `output_dir` | `./results` | Markdown output root |
| `paths` | `cache_dir` | `./.doc2md_cache` | resumability cache |
| `rclone` | `flags` | `["--progress", "--transfers=4"]` | extra rclone flags |
| `llm` | `base_url` | `http://localhost:11434` | Ollama endpoint |
| `llm` | `model` | `llama3.1:8b` | model name |
| `llm` | `timeout` | `120` | request timeout (s) |
| `llm` | `max_retries` | `3` | retry count with exponential backoff |
| `extraction` | `pymupdf_min_chars` | `100` | min chars to consider a PDF digital |
| `extraction` | `gibberish_threshold` | `0.3` | max non-printable ratio before falling back to OCR |
| `processing` | `batch_size` | `5` | files per batch |

## Caching / Resumability

JSON manifest in `cache_dir` tracks per-file:
- File content hash (SHA-256) — cache invalidates on file change
- Completed stages: `extract`, `order`, `classify`, `assemble`, `output`
- Output path and last-processed timestamp

Pipeline skips already-completed files unless `--force` is set. Intermediate page data is not yet persisted (re-extracted on partial resume).

## LLM Usage

The pipeline is designed to minimize LLM dependency. For digital PDFs, rule-based segmentation using PyMuPDF font metadata handles classification and chapter detection with no LLM calls. LLM calls (via `OllamaClient` with JSON-mode output) are used only for:

1. **Page number detection** — extract page number from OCR text (screenshots only)
2. **Duplicate detection** — borderline fuzzy matches (0.7–0.85 similarity) confirmed via LLM (screenshots only)
3. **Chapter boundary detection** — fallback when rule-based heading-level analysis is ambiguous (rare)

Responses are parsed with fallback handling for markdown fences and trailing commas. Failures degrade gracefully.

### Classification approach (rule-based)

For digital PDFs, `analysis/segmenter.py` uses PyMuPDF block dicts with font metadata:
- **Font size** — body text identified as the most common size; larger sizes → headings; smaller sizes in lower page half → footnotes
- **Font name** — heading fonts (e.g. `AGaramond-Titling`) detected as minority fonts at body size; used to catch title-case section headings
- **ALL CAPS** — body-sized all-caps text detected as section headings
- **Superscript numbers** — footnote IDs detected by spans with size < 80% of surrounding text
- **Boilerplate** — page numbers, URLs, and repeated lines filtered

For OCR pages (no block dicts), falls back to raw text heuristics: blank-line paragraph splitting, regex patterns for headings/footnotes/captions.

## Output Format

Each document produces a directory under `output_dir` containing one `.md` file per chapter:

```
results/
  book_title/
    chapter_01_front_matter.md
    chapter_02_introduction.md
    ...
```

Each chapter file contains:
- Heading hierarchy (Markdown `#`/`##`/etc.)
- Body text with joined page breaks and fixed hyphenation
- Figure captions as blockquotes (`> caption`)
- Index entries as list items
- Footnotes section (`[^N]: text`)
- Numbered bibliography under `## References`

## Dependencies

- Python ≥ 3.11
- PyMuPDF ≥ 1.24 — PDF text extraction and page rendering
- surya-ocr ≥ 0.17 — OCR for screenshots/scanned pages
- transformers ≥ 4.50, < 5 — pinned for Surya compatibility
- click ≥ 8.0 — CLI framework
- requests ≥ 2.31 — Ollama HTTP client
- rclone (external) — Google Drive sync
- Ollama (external) — local LLM inference server

## Quality

- 269+ tests, ~91% coverage
- Every module has a corresponding test file
- Comprehensive integration tests covering real-world academic PDF patterns
- Dev deps: pytest, pytest-cov, responses (HTTP mocking), playwright (e2e)

### Validated on

- *The Cambridge History of Science* (8 volumes, 342 PDFs, 2.97M words) — 80s total, zero failures
- *A History of Boston in 50 Artifacts* (209 Libby screenshots, 51.6k words) — 23 min OCR processing
- 9 books, 336 chapters, 2,831 section headings, 13,268 footnotes linked

## Known Limitations

- **Unsectioned chapters** — 14 files (mostly indexes, contributor lists, and continuous essays) have no section headings detected because the source PDFs genuinely lack them
- **Bibliographic line wrapping** — ~10 cases where short abbreviations in footnote references (e.g. "Cod. med. gr.") remain as broken short lines; fixing risks breaking the 316 math/number cases now correctly preserved
- **Page break gaps** — 19 sentences across 2.97M words have a blank line at a page boundary; fixing requires cross-page sentence analysis for negligible reader impact
- **Duplicate source files** — zip downloads from Cambridge Core sometimes contain duplicate PDFs; these must be deduplicated manually or by file hash before processing

## E-Book Reader (Implemented)

### Overview

Built-in web-based Markdown reader at `reader/`. No build step — vanilla JS + CSS, served via `python -m http.server`. Paginated two-column layout inspired by Libby/Kindle.

### Current features

- **Two-column paginated reading** (CSS multi-column layout with scrollLeft page turns)
- **Library view** — browse all books/chapters from `library.json`
- **Chapter navigation** — collapsible sidebar TOC
- **Themes** — light/dark/sepia (CSS custom properties)
- **Font size control** — 14-28px range, persisted
- **Footnote popovers** — click `[^N]` to see footnote without leaving page
- **Reading position persistence** — localStorage saves book/chapter/page
- **Progress bar** — page count, chapter word count + percentage, book word count
- **Keyboard navigation** — arrow keys, space, escape
- **`build_library.py`** — scans results/ and generates library.json with word counts

### Usage

```bash
python reader/build_library.py   # generate library.json
python -m http.server 8000       # serve from project root
# open http://localhost:8000/reader/
```

### Future reader enhancements

- Full-text search across chapters
- Bookmarks and highlights (Web Selection API)
- Font family selector (serif/sans-serif/dyslexia-friendly)
- Line spacing and margin controls
- "Time left in chapter" estimate
- Offline support (Service Worker)
- Desktop app wrapper (Tauri v2)

### Tech stack

| Component | Choice |
|---|---|
| Markdown→HTML | markdown-it + markdown-it-footnote (CDN) |
| Pagination | CSS multi-column layout + scrollLeft |
| Framework | Vanilla JS (~450 lines) |
| Themes | CSS custom properties |
| Serving | `python -m http.server` |

### Column bleed: diagnosis and solution

The two-column paginated reader suffered from text from adjacent pages bleeding into the visible area. This section documents the problem, failed approaches, and the working solution.

#### The problem

With CSS multi-column layout, content flows into columns that extend horizontally. To show one "page" (2 columns), the reader must shift the content and clip everything outside the visible area. Text from the next or previous page's columns bled into view, getting worse on later pages due to cumulative alignment drift.

#### Root cause

The browser places columns at intervals of `(actualColWidth + columnGap)`. With `column-count: 2`, the browser auto-calculates `actualColWidth` — and `2 * (actualColWidth + gap)` does **not** equal the container width. For example, at 1512px viewport: container is 1416px, but the actual two-column span is 1464px (2 × 732). Every page turn undershoots or overshoots by 48px (one gap width), accumulating across pages.

Key insight: **you cannot calculate the column step from container dimensions alone** — you must measure the actual rendered column positions from the DOM.

#### Failed approaches

1. **`translateX` + `overflow: hidden`** — `overflow: hidden` clips at the border/padding edge, not the content edge. Translated content that extends past the left edge of the container remains visible within the padding area. Sub-pixel rendering also causes bleed at the right edge.

2. **`clip-path: inset(0)`** — clips to the same boundary as `overflow: hidden`. Does not help.

3. **Computing `pageStep` from container width** — `pageStep = contentWidth` drifts because the browser's actual column step differs from `contentWidth / 2`. Using `column-width` CSS property (instead of `column-count`) also fails because `column-width` is a minimum suggestion — the browser may create more or fewer columns, especially on Retina displays.

4. **Reducing column width by 1px** — reduces the bleed but doesn't eliminate it, and the drift still accumulates.

5. **Headless vs headed browser differences** — headless Chromium and headed Chrome render columns differently. The bug only appeared in headed Chrome with Retina (2x) device scale. Always test pagination in headed Chrome at production resolution.

#### Working solution

Three elements combined:

1. **`scrollLeft` instead of `translateX`** — the browser's native scroll clipping is pixel-perfect. `inner.scrollLeft = offset` clips content exactly at the scroll boundary, unlike `translateX` which shifts content within the element's box and relies on `overflow: hidden` to clip.

2. **Measure actual column step from DOM** — `_measureColumnStep()` finds the first block elements' x-positions relative to the content container, computes the step between consecutive column starts. This gives the browser's actual column width + gap, not a calculated estimate.

3. **Set inner container width to `pageStep`** — `inner.style.width = pageStep + 'px'` ensures `overflow: hidden` clips exactly at the column boundary. Since `pageStep = 2 * actualColStep` and the inner container is that exact width, no partial third column can ever be visible.

#### Code pattern

```js
// Measure actual column step from rendered DOM
const actualColStep = _measureColumnStep(container);
state.pageStep = actualColStep * COLUMNS;

// Set inner width to match so overflow clips at column boundary
inner.style.width = state.pageStep + 'px';

// Navigate via scrollLeft (not translateX)
inner.scrollLeft = currentPage * state.pageStep;
```

### Design references

- [Libby architecture](https://rakuten.today/tech-innovation/meet-libby-overdrives-new-ereading-app.html) — augmented hybrid app, CSS column pagination
- [epub.js](https://github.com/futurepress/epub.js/) — CSS column pagination reference
- [CSS Multi-Column Book Layout](https://www.w3tutorials.net/blog/css-multi-column-multi-page-layout-like-an-open-book/)

## Non-Goals (Current Scope)

- Cloud LLM support (currently Ollama-only)
- Table extraction / reconstruction
- Image/figure extraction (captions only)
- Multi-language OCR
- Intermediate data persistence (pages are re-extracted on partial resume)
