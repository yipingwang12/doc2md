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

With `column-count: 2` and gap `G`, the browser creates columns of width `(W - G) / 2` within container width `W`. Two columns plus one gap fill the container exactly: `2 * colWidth + G = W`. But the page step — the distance between consecutive page starts — is `W + G`, not `W`. The extra `G` is the inter-page gap between the last column of one page and the first column of the next.

The original code used `pageStep = contentWidth` (missing `+ gap`), causing 48px undershoot per page turn, accumulating across pages. A subsequent fix attempt introduced DOM measurement of column positions (`_measureColumnStep()`) and set the inner container width to the measured `pageStep`. This created a circular dependency: setting the width changed the column layout, invalidating the measurement. Example at 1512px viewport: natural container width 1416px → measured colStep 732 → set inner width to 1464 → browser recalculates colWidth to 708 → actual colStep becomes 756 → 48px drift per page.

#### Failed approaches

1. **`translateX` + `overflow: hidden`** — `overflow: hidden` clips at the border/padding edge, not the content edge. Translated content that extends past the left edge of the container remains visible within the padding area. Sub-pixel rendering also causes bleed at the right edge.

2. **`clip-path: inset(0)`** — clips to the same boundary as `overflow: hidden`. Does not help.

3. **`pageStep = contentWidth`** — missing `+ gap`. Drifts by one gap width (48px) per page turn.

4. **Reducing column width by 1px** — reduces but doesn't eliminate; drift still accumulates.

5. **DOM measurement + inner width override** — `_measureColumnStep()` measured actual column positions, then set `inner.style.width = pageStep`. The width change triggers a reflow that changes column widths, invalidating the measurement. Same 48px drift, different cause.

6. **Sidebar recalc via `requestAnimationFrame`** — sidebar slides in/out via CSS `margin-left` transition (0.25s). `recalcPages()` in a `requestAnimationFrame` fires before the transition completes, measuring the old width.

#### Working solution

1. **`scrollLeft` instead of `translateX`** — browser's native scroll clipping is pixel-perfect. `inner.scrollLeft = offset` clips exactly at the scroll boundary.

2. **`pageStep = contentWidth + COLUMN_GAP`** — correct arithmetic. No DOM measurement, no container width override, no circular dependency. With `column-count: 2`, the browser fills the container exactly, so no partial third column can ever be visible.

3. **`clip-path: inset(0 1px 0 0)`** — 1px right-edge safety margin for sub-pixel Retina rounding.

4. **Sidebar: `transitionend` listener** — `recalcPages()` fires only after the sidebar's CSS transition completes, ensuring the width measurement reflects the final layout.

#### Code pattern

```js
// pageStep = container width + inter-page gap. No measurement needed.
state.pageStep = contentWidth + COLUMN_GAP;

// Navigate via scrollLeft (not translateX)
inner.scrollLeft = currentPage * state.pageStep;
```

#### Testing

Playwright visual tests (`screenshots/test_bleed.py`) verify column alignment across pages 1–15, with and without sidebar, at 1512×900 Retina (2x). Use instant scroll (`scrollBehavior: 'auto'`) for accurate screenshots — smooth scroll animation causes false positives.

### Design references

- [Libby architecture](https://rakuten.today/tech-innovation/meet-libby-overdrives-new-ereading-app.html) — augmented hybrid app, CSS column pagination
- [epub.js](https://github.com/futurepress/epub.js/) — CSS column pagination reference
- [CSS Multi-Column Book Layout](https://www.w3tutorials.net/blog/css-multi-column-multi-page-layout-like-an-open-book/)

## TODO: Index Linking

### Current state

- 7 index chapters exist in output (one per Cambridge Science volume)
- Index entries are classified as `body` blocks — the `index` block type is defined in `TextBlock` and handled in `markdown_writer.py` but never assigned by the segmenter
- Entries are plain text with source PDF page numbers (e.g., `"Abbe, Ernst 246"`); no links to main text
- Index hierarchies (sub-entries, "see also" cross-refs) are flattened

### Matching strategy: page-guided text search

Both the page number and the term are available during pipeline execution. Used together they are much stronger than either alone.

1. **Build page_number → chapter/section map** from `Page.page_number` + `TextBlock.page_index` + chapter assignment
2. **Parse index entries** into structured `(term, [page_numbers])` pairs; handle sub-entries, page ranges (`280–291`), and cross-refs (`see also X`)
3. **For each (term, page_number)**: look up which chapter contains that page, search for the term verbatim in that chapter's text
4. **Only emit a link when the term actually appears** near the indicated page (±1 page for digital PDFs, ±2 for OCR); skip otherwise

### Screenshot / OCR books

Same strategy applies, with two adjustments:

- **Fuzzy text matching** — OCR errors break verbatim search. Normalize unicode, collapse whitespace, use similarity threshold. Switch exact vs fuzzy based on `Page.extraction_method` (`pymupdf` vs `surya`)
- **Wider page window** — `Page.page_number` is LLM-detected for screenshots, may be off. Use ±2 page search window; require stronger text match to compensate

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| `Page.page_number` is None | Skip — no match without page mapping |
| Common-word terms ("Russia", "war") | Page constraint narrows search; safe |
| Multiple occurrences on same page | Link to section heading, not specific line |
| Page ranges (280–291) | Search all pages in range; link to section containing start page |
| OCR mangles term | Fuzzy match for OCR sources; skip if ambiguous |
| Cross-references ("see also X") | Link to other index entries, not body text; or skip |

### Implementation notes

- Must run during pipeline execution (stage 7–8) when `Document.pages` and `Chapter.blocks` are both in memory
- Segmenter needs rules to detect and classify index content as `index` block type
- Markdown writer emits anchors at match sites and hyperlinks in the index chapter
- Conservative: unmatched entries remain as plain text — no guessing

## Non-Goals (Current Scope)

- Cloud LLM support (currently Ollama-only)
- Table extraction / reconstruction
- Image/figure extraction (captions only)
- Multi-language OCR
- Intermediate data persistence (pages are re-extracted on partial resume)
