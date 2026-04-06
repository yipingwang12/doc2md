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
  link-index <volume_dir>  Link index entries to chapter files
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

- 354+ tests, ~91% coverage
- Every module has a corresponding test file
- Comprehensive integration tests covering real-world academic PDF patterns
- Dev deps: pytest, pytest-cov, responses (HTTP mocking), playwright (e2e)

### Validated on

- *The Cambridge History of Science* (8 volumes, 342 PDFs, 2.97M words) — 80s total, zero failures
- *A History of Boston in 50 Artifacts* (209 Libby screenshots, 51.6k words) — 23 min OCR processing
- 9 books, 299 chapters (deduped), 2,831 section headings, 13,268 footnotes linked, 18,761 index links

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

## Index Linking (Implemented)

### Overview

Post-processing step that parses index chapters, matches entries to content chapters by page number, and rewrites the index with markdown hyperlinks. Implemented in `assembly/index_linker.py`, invoked via `doc2md link-index <volume_dir>`.

### Architecture

Runs as a **post-processing step on output files**, not inline in the pipeline. Reason: the pipeline processes one source PDF at a time, but index linking needs all chapters in a volume simultaneously. Reads `.md` files from the output directory, builds a page→chapter map from `NNN_pp_START_END_title` directory names.

### How it works

1. **`build_chapter_map()`** — parses directory names for page ranges, loads chapter text, sorts by start page. Prefers narrowest range when section dividers overlap individual chapters.
2. **`parse_index_md()`** — state-machine parser handles main entries, sub-entries (indented/following), `(cont.)` continuations, page ranges with abbreviated ends (`516–17` → 516–517), "See also" cross-refs (including targets on next line), wrapped lines, page-number headings (stripped)
3. **`_term_variants()`** — generates search variants: reversed names ("Abelard, Peter" → "Peter Abelard", "Abelard"), preposition stripping ("medicine in Africa" → "medicine")
4. **`_term_in_chapter()`** — case-insensitive substring search using all variants
5. **`render_linked_index()`** — for each page ref, finds covering chapter; if term variant found in chapter text, renders as relative markdown link `[516](../dir/chapter.md)`; unmatched entries stay as plain text

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
| **Total** | **18,761** | | **6 of 7 clean** |

V1 and Boston Artifacts skipped (no `_pp_N_N_` directory naming).

### Known issues

1. **V4 semicolon-delimited format** — v4's index uses semicolons to separate sub-topics within flowing multi-line entries (e.g. `and chemistry, 379; establishment of, 88–9, 512; and navigation, 827`). The newline-based parser mishandles these, producing 113 corrupt "See also" lines. Needs a semicolon-aware sub-entry parser.

2. **Years parsed as page numbers** — entries like `"French Revolution, 1789"` have the year extracted as a page ref. Affects v6/v7/v8 where max page < 900. Fix: filter refs exceeding the volume's max page number.

3. **Unmatched generic sub-entries** — terms like "overview", "general discussion", "in optics" don't appear verbatim in chapter text (~20–30% of refs). These are correctly left as plain text by the conservative matching approach.

4. **`index` block type unused** — the segmenter still classifies index content as `body` blocks. The `index` type in `TextBlock` is defined and handled by `markdown_writer.py` but never assigned. Orthogonal to linking — could be added as a post-chapter-detection reclassification step.

## TODO: Cross-Volume Entity Search

### Goal

Search for a person, concept, or term across all processed volumes and extract surrounding paragraphs — even when subsequent sentences use pronouns or paraphrases instead of the original term.

### Requirements

- Query interface (CLI + reader UI) that searches all volumes' markdown output
- Paragraph-level context extraction, not just matching lines
- Coreference-aware: "Einstein" match should include following sentences that say "he" or "the physicist"
- Results grouped by volume/chapter with source location

### Approaches

Five broad strategies, from simplest to most capable:

#### 1. Sparse retrieval (keyword search)

Inverted index + BM25 ranking. Tokenize documents, rank by term frequency. Fast, interpretable, no AI. Struggles with synonyms and paraphrases — "Einstein" won't match "the physicist".

#### 2. Dense retrieval (embedding search)

Bi-encoder models encode query and passages into dense vectors; retrieve by cosine similarity. Handles semantic similarity ("quantum physicist" matches Einstein passages even without his name). ColBERT v2 uses late interaction (token-level comparison) for better precision. Matryoshka embeddings allow variable dimensions for storage/quality tradeoff.

#### 3. Named entity recognition + entity linking

NER models identify entity mentions and classify them (person, place, org). Entity linking resolves mentions to a knowledge base (e.g. "Albert" on page 391 → Wikidata Q60093 = Albertus Magnus). Zero-shot NER (GLiNER) can find entities of any user-specified type without fine-tuning.

#### 4. RAG (retrieval-augmented generation)

Chunk documents into paragraphs, embed each chunk, index in a vector store, retrieve top-k for a query, pass to LLM for synthesis. Sidesteps the coreference problem — the LLM reads retrieved paragraphs and naturally understands that "he" refers to Einstein.

#### 5. GraphRAG (graph-based retrieval)

Extract entities and relations from text into a knowledge graph. Use community detection and graph structure to answer queries that span many documents. Microsoft GraphRAG (2024) builds the graph via LLM calls, then uses it for multi-document synthesis. RAPTOR recursively clusters and summarizes chunks into a tree for multi-level retrieval.

### Coreference resolution

The key sub-problem: linking "Einstein... he... the physicist... his theory" across sentences.

- **Transformer coref models** — SpanBERT-based approaches predict which mentions refer to the same entity
- **Autoregressive structured prediction** — Facebook's 2023 approach frames coref as seq2seq, near-human performance
- **LLM-based coref** — prompt an LLM to resolve coreferences; works well for small contexts but expensive at scale

### Candidate packages

#### Dense retrieval / embedding search

| Package | Install | Notes |
|---|---|---|
| sentence-transformers | `pip install sentence-transformers` | Best model ecosystem; models 100MB–1GB; fully local |
| FAISS | `pip install faiss-cpu` | Meta's vector search; fast ANN; ~30MB; index-only (no embedding) |
| ChromaDB | `pip install chromadb` | Embedded vector DB with auto-embedding; SQLite-backed; turnkey |
| LanceDB | `pip install lancedb` | Lighter alternative to Chroma; columnar format; zero server |
| sqlite-vec | `pip install sqlite-vec` | SQLite extension for vectors; minimal footprint |

#### Named entity recognition

| Package | Install | Notes |
|---|---|---|
| GLiNER | `pip install gliner` | Zero-shot NER — pass custom entity types at inference; ~500MB model |
| spaCy | `pip install spacy` | Fast, production-grade; fixed entity types unless trained |
| gliner-spacy | `pip install gliner-spacy` | Wraps GLiNER into a spaCy pipeline |

#### Coreference resolution

| Package | Install | Notes |
|---|---|---|
| fastcoref | `pip install fastcoref` | Current best standalone; ~1GB model; `FCoref` (speed) or `LingMessCoref` (accuracy) |
| maverick-coref | `pip install maverick-coref` | Newer (2024), strong benchmarks |
| coreferee | `pip install coreferee` | spaCy plugin; lighter but less accurate |

#### RAG frameworks (Ollama-compatible)

| Package | Install | Notes |
|---|---|---|
| LlamaIndex | `pip install llama-index llama-index-llms-ollama` | First-class Ollama support; best indexing abstractions |
| Haystack v2 | `pip install haystack-ai` | Clean 2024 rewrite; `OllamaGenerator` component |
| txtai | `pip install txtai` | All-in-one: embeddings + RAG + workflows |

#### GraphRAG

| Package | Install | Notes |
|---|---|---|
| Microsoft GraphRAG | `pip install graphrag` | Most mature (20k+ stars); entity graph via LLM; heavy indexing compute |
| nano-graphrag | `pip install nano-graphrag` | Lightweight reimplementation; simpler; easier to customize |
| LightRAG | `pip install lightrag-hku` | 2024 paper; dual-level retrieval; simpler than MS GraphRAG |

#### Knowledge graph extraction

| Package | Install | Notes |
|---|---|---|
| REBEL | HuggingFace `Babelscape/rebel-large` | Single forward pass → (subj, rel, obj) triples; ~220 fixed relation types |
| GLiNER + GLiREL | `pip install gliner glirel` | Zero-shot NER + relation extraction with custom types |
| relik | `pip install relik` | State-of-the-art entity linking + relation extraction |

#### Full-text search

| Package | Install | Notes |
|---|---|---|
| sqlite-utils | `pip install sqlite-utils` | One-liner FTS5: `db["docs"].enable_fts(["body"])` |
| tantivy-py | `pip install tantivy` | Rust-based full-text engine; very fast |

### Proposed implementation plan

Three-phase approach, each phase standalone and useful:

#### Phase 1: Index-guided search (no new dependencies)

Leverage the 18,761 existing index links as a pre-built entity-to-passage map. Build a CLI command (`doc2md search <term>`) that:

1. Scans all linked index files for the search term
2. Follows the markdown links to extract the referenced chapter paragraphs
3. Groups results by volume/chapter
4. Outputs matching passages with context

This covers the "look up Albertus Magnus across all volumes" use case with zero additional dependencies — the index linking already solved the hard problem of knowing where entities are discussed.

#### Phase 2: Full-text search (add `sqlite-utils`)

Build a search index over all chapter markdown files:

1. `doc2md build-search` chunks all chapters into paragraphs, indexes in SQLite FTS5
2. `doc2md search <term>` queries FTS5 with BM25 ranking, returns paragraphs with context
3. Combine with Phase 1: index-guided results first (high precision), FTS5 results second (high recall)
4. Reader UI: add search bar that queries an API endpoint or a pre-built JSON index

Handles entities not in the book index, and finds mentions in volumes without indexes (v1, Boston Artifacts).

#### Phase 3: Semantic search + coreference (add `sentence-transformers`, `faiss-cpu`, `fastcoref`)

1. Embed all paragraphs with a local model (e.g. `all-MiniLM-L6-v2`, 80MB)
2. Index in FAISS for sub-second similarity search
3. Run `fastcoref` on retrieved paragraphs to expand matches to coreferent mentions
4. Optionally pass retrieved + coref-expanded passages through Ollama for synthesis

This handles the "he/the physicist" problem and semantic queries ("who contributed to medieval alchemy?").

#### Why not GraphRAG first

GraphRAG (Phase 4, if needed) requires LLM calls for every chunk during indexing — expensive even with Ollama on a 3M-word corpus. The three-phase plan above gets 90% of the value with minimal compute. GraphRAG would add value for complex multi-hop queries ("how did Islamic astronomy influence European cosmology through translation?") but can wait until the simpler phases prove insufficient.

## Non-Goals (Current Scope)

- Cloud LLM support (currently Ollama-only)
- Table extraction / reconstruction
- Image/figure extraction (captions only)
- Multi-language OCR
- Intermediate data persistence (pages are re-extracted on partial resume)
