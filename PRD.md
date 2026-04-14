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
| 3 | **Clean** | `assembly/cleaner` | Normalize ligatures and PDF control char encoding (PUA, ayin/alef); strip repeated headers/footers, page numbers, and URL boilerplate |
| 4 | **Order** | `ordering/dedup`, `ordering/reorder` | Deduplicate pages (hash → fuzzy → LLM fallback); detect page numbers via LLM; reorder; warn on gaps (screenshots only) |
| 5 | **Classify** | `analysis/segmenter`, `analysis/classifier` | Rule-based segmentation using PyMuPDF block structure and font metadata (size, name); falls back to raw text heuristics for OCR pages. Splits merged footnote blocks at superscript boundaries |
| 6 | **Structure** | `analysis/chapter_detector` | Rule-based chapter detection from heading levels; LLM fallback only when rules are ambiguous. Merges consecutive heading-only blocks into combined titles |
| 7 | **Assemble** | `assembly/footnotes`, `assembly/citations`, `assembly/merger` | Link footnotes (merging orphan continuations); extract bibliography; then merge body blocks across page breaks with hyphenation fix and sentence joining |
| 8 | **Output** | `output/markdown_writer` | Render each chapter to a separate `.md` file with footnotes section and numbered bibliography |
| 9 | **Index** | `assembly/index_linker` | Post-processing: parse index entries, match to chapters by page range, rewrite index with hyperlinks (via `link-index` CLI) |

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
  split     Split a single-file markdown into per-chapter directories
              --output-dir PATH   Override output directory
              --artifacts         Split at individual artifact/item level
  link-index <volume_dir>  Link index entries to chapter files
  search <term>  Cross-volume entity search via linked indexes
              --output-dir PATH   Override results directory
              --context N         Surrounding paragraphs
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

- 405+ tests, ~86% coverage
- Every module has a corresponding test file
- Comprehensive integration tests covering real-world academic PDF patterns
- Dev deps: pytest, pytest-cov, responses (HTTP mocking), playwright (e2e)

### Validated on

- *The Cambridge History of Science* (8 volumes, 342 PDFs, 2.97M words) — 80s total, zero failures
- *A History of Boston in 50 Artifacts* (209 Libby screenshots, 59.6k words, 59 chapters) — 23 min OCR, 85% index entry match rate
- 10 books, 358 chapters, 2,831 section headings, 13,268 footnotes linked, 20,427 index links

## Processing Log

### The Wood at Midwinter (Susanna Clarke)

- **Source**: 26 Libby screenshots (landscape spreads), 36 MB, synced from Google Drive
- **Pipeline**: `is_libby_spread()` → True → `extract_screenshot_spread()` (split at midpoint, batch OCR, skip image-only pages)
- **OCR**: Surya, CPU only (M3 Max, MPS disabled by sandbox), **1.8 min**
- **Output**: 414 lines, single chapter ("Untitled") — short story with no internal headings
- **Post-processing**: manual `split_markdown()` with explicit `ChapterDef` list (4 sections: front matter, story, afterword, publisher info); auto-detection catches `Afterword: Snow` via `_TITLED_SECTION_RE`
- **No index** in source

### Morocco: Globalization and Its Consequences (Cohen & Jaidi)

- **Source**: 103 browser screenshots (1366×768, full-screen captures of VBooks web viewer with Ubuntu panel + Chrome tabs + dock visible), 38 MB
- **Current pipeline** (after optimizations — see `morocco_processing_notes.md` for history): `is_browser_screenshot()` → True → `extract_screenshots(auto_number=True)` with chrome cropping + batched OCR; no LLM calls
- **OCR**: Surya on MPS/GPU, `_ocr_batched(batch_size=16)`, **~16 min** end-to-end, 7 batches, zero thermal throttling
- **Output**: 5,411 lines (30% shorter than the original 7,118-line uncropped run — browser chrome removed). Split into 4 clean directories: `010_preface`, `020_conclusion_what_future_for_a_development_policy`, `030_bibliography`, `040_index`. Index linked with 293 hyperlinks.
- **Remaining quality gap**: Morocco's 4 real body chapters have no regex-detectable markers; they live as a ~4000-line blob inside `010_preface/`. Fixable only with LLM page-number detection or manual `ChapterDef` list.
- **Full history** (bugs, thermal issues, A/B tests, MPS setup, chapter splitter hardening): see [`morocco_processing_notes.md`](./morocco_processing_notes.md)

## Known Limitations

- **Unsectioned chapters** — 14 files (mostly indexes, contributor lists, and continuous essays) have no section headings detected because the source PDFs genuinely lack them
- **Bibliographic line wrapping** — ~10 cases where short abbreviations in footnote references (e.g. "Cod. med. gr.") remain as broken short lines; fixing risks breaking the 316 math/number cases now correctly preserved
- **Page break gaps** — 19 sentences across 2.97M words have a blank line at a page boundary; fixing requires cross-page sentence analysis for negligible reader impact
- **Duplicate source files** — zip downloads from Cambridge Core sometimes contain duplicate PDFs; `build_library.py` deduplicates by SHA-256 content hash; section divider PDFs (Part titles) are filtered
- **PDF control char encoding** — Cambridge UP PDFs encode Semitic transliteration characters (ayin ʿ, alef ʾ) as ASCII control codes U+0002/U+0003; cleaner maps these to Unicode modifier letters U+02BF/U+02BE

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
- **`build_library.py`** — scans results/ and generates library.json with word counts; deduplicates section dividers by content hash; skips metadata dirs; extracts titles from `###` headings with multiline continuation; supports multi-file chapters (front matter + content)

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

## Chapter Splitter (Implemented)

### Overview

Post-processing tool that splits a single-file markdown book into per-chapter directories. Implemented in `output/chapter_splitter.py`, invoked via `doc2md split`.

### How it works

1. **TOC detection** — finds "Contents" section, identifies duplicate markers (TOC vs body) to locate where body content begins
2. **Section-level detection** — finds PART headers, named sections (Preface, Introduction, Notes, Bibliography, Index), titled sections (CONCLUSION, APPENDIX); handles wrapped multi-line titles and HTML tag stripping
3. **Artifact-level detection** (`--artifacts`) — within PART sections, finds individual items via numbered headings (`N. Title`) or first figure references (`FIGURE N.1`); backs up to preceding blank line for figure-only splits; extracts titles from TOC and Appendix

### Directory naming

- With page ranges (Cambridge): `010_pp_1_6_introduction/`
- Without page ranges (Boston): `010_introduction/`, `050_1_mattapan_banded_rhyolite/`

Original single-file directory archived as `.orig` to avoid duplication.

## Index Linking (Implemented)

### Overview

Post-processing step that parses index chapters, matches entries to content chapters, and rewrites the index with markdown hyperlinks. Implemented in `assembly/index_linker.py`, invoked via `doc2md link-index <volume_dir>`.

### Two linking modes

1. **Page-range mode** (Cambridge) — directories named `NNN_pp_START_END_title`; `build_chapter_map()` maps page numbers to chapters; each index page ref links to its covering chapter
2. **Pageless mode** (Boston/Libby) — directories without `_pp_` naming; `build_chapter_map_pageless()` loads all chapters; each index term is searched across all chapters via `_term_in_chapter()`; links to every matching chapter

Falls back automatically: tries page-range mode first, pageless if no `_pp_` dirs found.

### Term matching

`_term_variants()` generates search variants:
- Reversed names: "Abelard, Peter" → "Peter Abelard", "Abelard"
- Parenthetical stripping: "AMS (accelerated mass spectrometer) dating" → "AMS dating"
- Colon/semicolon stripping: "Beacon Hill: as fashionable neighborhood" → "Beacon Hill"
- HTML tag stripping: `<b>Boston Town Records</b>` → "Boston Town Records"
- Preposition phrase dropping: "medicine in Africa" → "medicine"

### Index parsing

`parse_index_md()` handles main entries, sub-entries, `(cont.)` continuations, abbreviated page ranges (`516–17` → 516–517), "See also" cross-refs, wrapped continuation lines (detected by mid-sentence line endings), and bibliography spillover detection (stops at double blank lines or `[^YEAR]:` patterns).

### Idempotency

Saves original index as `.orig.md` on first run. Subsequent runs always read from `.orig.md`, preventing corruption from re-parsing linked output.

### Results

| Volume | Links | Link rate | Status |
|---|---:|---:|---|
| v2 Medieval | 3,043 | 72% | Clean |
| v3 Early Modern | 2,136 | 82% | Clean |
| v4 18th Century | 2,822 | 59% | 113 corrupt "See also" lines (semicolon format) |
| v5 Modern Phys/Math | 3,271 | 88% | Clean |
| v6 Modern Bio/Earth | 2,654 | 80% | Clean |
| v7 Modern Social | 2,753 | 87% | Clean |
| v8 National/Global | 2,082 | 80% | Clean |
| Boston Artifacts | 1,666 | 85% | Pageless mode, 59 artifact-level chapters |
| **Total** | **20,427** | | **7 of 8 clean** |

### Known issues

1. **V4 semicolon-delimited format** — v4's index uses semicolons to separate sub-topics within flowing multi-line entries. The newline-based parser mishandles these, producing 113 corrupt "See also" lines. Needs a semicolon-aware sub-entry parser.

2. **Years parsed as page numbers** — entries like `"French Revolution, 1789"` have the year extracted as a page ref. Affects v6/v7/v8 where max page < 900. Fix: filter refs exceeding the volume's max page number.

3. **Unmatched generic sub-entries** — terms like "overview", "general discussion", "in optics" don't appear verbatim in chapter text (~15–20% of refs). Correctly left as plain text by the conservative matching approach.

4. **`index` block type unused** — the segmenter still classifies index content as `body` blocks. The `index` type in `TextBlock` is defined and handled by `markdown_writer.py` but never assigned. Orthogonal to linking.

## Cross-Volume Entity Search

### Overview

Search for a person, concept, or term across all processed volumes and extract surrounding paragraphs. Implemented in `assembly/search.py`, invoked via `doc2md search <term>`.

### Phase 1: Index-guided search (Implemented)

Leverages the 18,761 existing index links as a pre-built entity-to-passage map. Zero additional dependencies.

`doc2md search <term> [--context N]`:

1. Scans all volumes' linked index files for the search term
2. Follows markdown links to extract referenced chapter paragraphs
3. Groups results by volume/chapter with display names (e.g. "Islamic Culture (pp. 27–61)")
4. Outputs matching passages with optional surrounding paragraph context

### Future phases

#### Phase 2: Full-text search (add `sqlite-utils`)

`doc2md build-search` chunks all chapters into paragraphs, indexes in SQLite FTS5. Combine with Phase 1: index-guided results first (high precision), FTS5 second (high recall). Covers volumes without indexes (v1, Boston Artifacts).

#### Phase 3: Semantic search + coreference (add `sentence-transformers`, `faiss-cpu`, `fastcoref`)

Embed paragraphs with a local model, index in FAISS, run coreference resolution on retrieved passages to expand "Einstein" → "he" / "the physicist". Optionally pass through Ollama for synthesis.

#### Why not GraphRAG first

GraphRAG requires LLM calls for every chunk during indexing — expensive on a 3M-word corpus. Phases 1–3 get 90% of value with minimal compute. GraphRAG would add value for complex multi-hop queries but can wait until simpler phases prove insufficient.

## Non-Goals (Current Scope)

- Cloud LLM support (currently Ollama-only)
- Table extraction / reconstruction
- Image/figure extraction (captions only)
- Multi-language OCR
- Intermediate data persistence (pages are re-extracted on partial resume)
