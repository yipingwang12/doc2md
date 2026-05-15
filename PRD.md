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

## Credentials

`ANTHROPIC_API_KEY` — stored in `.env` at the repo root (git-ignored). Required for Claude API vision extraction (see [OCR Engines](docs/OCR_ENGINES.md)).

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

## OCR Engine Cascade

Screenshot and scanned-PDF extraction goes through a pluggable engine abstraction at `src/doc2md/extract/ocr_engines/`. See [OCR Engines](docs/OCR_ENGINES.md) for full engine reference, cascade configuration, vision-model alternatives, and future work.

### Engine selection summary

| Criterion | Cascade (current) | Qwen2.5-VL (cloud) | Claude API |
|---|---|---|---|
| Speed (Boston 418 pp) | ~7 min | ~15 hrs / 10× instances | ~90 min (batch) |
| Cost | Free | ~$25–35 / full library | ~$1.78/book |
| Copyright refusals | None | None | Book-dependent |
| Local-first | Yes | No | No |
| Pipeline stages replaced | 0 | 2–5 | 2–6 |

Best fit: cascade for bulk re-processing; Claude API for new books with known cascade regressions; Qwen2.5-VL cloud for library-scale processing where copyright refusals are a concern.

## Dependencies

### Core (required)

- Python ≥ 3.11
- PyMuPDF ≥ 1.24 — PDF text extraction and page rendering
- surya-ocr ≥ 0.17 — OCR for screenshots/scanned pages (always-available cascade fallback)
- transformers ≥ 4.50, < 5 — pinned for Surya compatibility
- click ≥ 8.0 — CLI framework
- requests ≥ 2.31 — Ollama HTTP client
- rclone (external) — Google Drive sync
- Ollama (external) — local LLM inference server

### Optional OCR cascade (`pip install doc2md[cascade]`)

- pytesseract ≥ 0.3.10 + `tesseract` binary — Tesseract engine (cross-platform, CPU-bound, fastest primary stage for clean English)
- ocrmac ≥ 1.0 (darwin only) — Apple Vision engine via `VNRecognizeTextRequest` (Neural Engine, avoids GPU thermal contention)

Cascade stages missing their Python dependency are silently skipped at runtime; Surya always stays as the final fallback.

## Known Limitations

- **Unsectioned chapters** — 14 files (mostly indexes, contributor lists, and continuous essays) have no section headings detected because the source PDFs genuinely lack them
- **Bibliographic line wrapping** — ~10 cases where short abbreviations in footnote references (e.g. "Cod. med. gr.") remain as broken short lines; fixing risks breaking the 316 math/number cases now correctly preserved
- **Page break gaps** — 19 sentences across 2.97M words have a blank line at a page boundary; fixing requires cross-page sentence analysis for negligible reader impact
- **Duplicate source files** — zip downloads from Cambridge Core sometimes contain duplicate PDFs; `build_library.py` deduplicates by SHA-256 content hash; section divider PDFs (Part titles) are filtered
- **PDF control char encoding** — Cambridge UP PDFs encode Semitic transliteration characters (ayin ʿ, alef ʾ) as ASCII control codes U+0002/U+0003; cleaner maps these to Unicode modifier letters U+02BF/U+02BE
- ~~**Cascade image-only page over-escalation**~~ — fixed: `default_quality_check` now returns `True` for empty `raw_text`, short-circuiting at Tesseract for image-only pages
- **Cascade title-detection regression** — Tesseract and Apple Vision don't provide font metadata (block dicts), so their pages bypass `analysis/segmenter.py`'s font-based title/heading classification. Pages that would have been classified as headings via font size/name in a Surya-only run fall through to raw-text heuristics in the cascade run

## Non-Goals (Current Scope)

- Cloud LLM support (currently Ollama-only)
- Table extraction / reconstruction
- Multi-language OCR
- Intermediate data persistence (pages are re-extracted on partial resume)

## Reference Docs

- [OCR Engines](docs/OCR_ENGINES.md) — engine abstraction, cascade config, vision-model alternatives (Qwen, Claude API), future work
- [Processing Log](docs/PROCESSING_LOG.md) — per-book run history, quality stats, library-scale strategy
- [Pipeline Components](docs/PIPELINE_COMPONENTS.md) — output format, chapter splitter, index linking, search, academic paper pipeline
- [E-Book Reader](docs/READER.md) — reader features, column bleed fix, tech stack
