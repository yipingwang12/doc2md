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

`ANTHROPIC_API_KEY` — stored in `.env` at the repo root (git-ignored). Required for Claude API vision extraction (see Vision-Model Alternatives).

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

Screenshot and scanned-PDF extraction goes through a pluggable engine abstraction at `src/doc2md/extract/ocr_engines/`. Every engine implements the same `OcrEngine` protocol:

```python
class OcrEngine(Protocol):
    name: str
    def ocr_batch(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool = False,
    ) -> list[OcrResult]: ...
```

`OcrResult` wraps the existing `Page` model with a `confidence: float` (0..1 mean per-line confidence, engine-specific scale) and a `line_count: int`. The quality signals let downstream code decide whether a page's OCR is good enough to keep.

### Available engines

| Engine | File | Strengths | Weaknesses | Dep |
|---|---|---|---|---|
| `TesseractEngine` | `ocr_engines/tesseract.py` | Fastest on CPU (~0.2 sec/half-page on Boston); lightest thermal footprint; good on clean English | Poor on math, non-Latin scripts, complex layouts; no block metadata | `pytesseract` + `tesseract` binary |
| `AppleVisionEngine` | `ocr_engines/apple_vision.py` | Fast on Apple Silicon Neural Engine; no GPU contention; handles layout automatically | macOS only; weaker on math/unusual fonts | `ocrmac` (macOS only) |
| `SuryaEngine` | `ocr_engines/surya.py` | Most capable on math, non-Latin scripts, unusual layouts; provides rich block metadata that powers font-based classification | Slowest; thermal-stress under sustained CPU load; best with GPU/MPS | `surya-ocr` (core dep) |
| `ClaudeApiEngine` | `ocr_engines/claude_api.py` | Frontier model; structure-preserving markdown in one pass; zero local compute; no thermal risk | Requires internet + API key; ~$0.003–0.004/page at Sonnet pricing; copyright refusals on some narrative pages at reduced resolution; Haiku hallucinates footnote defs | `anthropic`, `httpx` |
| `CascadeEngine` | `ocr_engines/cascade.py` | Runs multiple engines in order with per-page quality gating — only escalates to the next engine on pages that fail the check | — | n/a |

### Default cascade

`build_default_cascade(folder=None)` builds a **Tesseract → Apple Vision → Surya** cascade, dynamically including only the stages whose Python dependency is importable. Surya is always the final unconditional fallback (it's a core dep). Column preprocessing (from `chrome_cropper.detect_column_bounds()`) is applied to Tesseract and Apple Vision stages when the folder has multi-column layout; Surya runs on full content pages.

```python
CascadeEngine([
    (TesseractEngine(columns=cols, lang="eng"), default_quality_check),
    (AppleVisionEngine(columns=cols), default_quality_check),
    (SuryaEngine(), None),  # final stage, accepted unconditionally
])
```

### Per-page quality check

`default_quality_check()` rejects a result (triggering fallback to the next stage) if:
1. Mean confidence < `min_confidence` (default 0.60)
2. Line count < `min_lines` (default 3)
3. Non-printable character ratio > 0.30

Each stage runs on all items first, then the cascade re-runs failed items through the next stage. Page numbering (`auto_number=True`) is applied at the very end so page numbers stay sequential regardless of which engine produced each page.

### Wiring

`extract_screenshots(folder)` and `extract_screenshot_spread(folder)` default to `build_default_cascade(folder)` and `build_default_cascade()` respectively (the latter skips column detection because Libby spread halves are already single-column). Both accept an optional `engine` kwarg so tests and benchmarks can bypass the cascade with a bare `SuryaEngine()` or a mock.

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

Cascade stages missing their Python dependency are silently skipped at runtime; Surya always stays as the final fallback. The cascade is the default for screenshot folders but can be bypassed by passing `engine=SuryaEngine()` explicitly.

## Quality

- 506+ tests, ~90% coverage
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

### A History of Boston in 50 Artifacts (Joseph M. Bagley)

- **Source**: 209 Libby landscape spread screenshots (3024×1642 each, 418 half-pages after midpoint split)
- **Original run** (Surya-only, CPU): 23 min OCR, 59 clean chapter directories, 85% index link rate (1,666 links). See archived output under `results/boston_artifacts/` and backup `results_archive/boston_artifacts_2026-04-15/`.
- **Cascade run** (Tesseract → Apple Vision → Surya, MPS enabled): **~7 min** wall-clock (~2.5× faster). Tesseract and Apple Vision handled nearly all pages; Surya only recognized ~9 text lines across 2 small fallback batches. Output at `results/a_history_of_boston_in_50_artifacts/chapter_01_untitled.md` (6303 lines vs 6158 for the original — within 2.5%).
- **Observed quality deltas vs the original**:
  1. **Title detection regression** — original: `# A HISTORY` / `### OF BOSTON`; cascade: `# Untitled`. Root cause: Surya's `RecognitionPredictor` supplies block metadata (font name, size, bbox) that `analysis/segmenter.py` uses to classify title-styled headings. Tesseract and Apple Vision don't expose that metadata, so pages they successfully handle fall through to the raw-text classifier, which doesn't recognize ALL-CAPS title spans.
  2. **More raw OCR noise on image-heavy pages** — cover and copyright pages show strings like `Ziwi2` / `@ut-q` / `iv &@h OA` in the cascade output. Surya has a built-in `MIN_BBOXES=3` gate that silently skips image-only pages; Tesseract and Apple Vision run on everything and produce garbled output on graphic regions.
  3. **Image-only pages cascade through all three engines** — `default_quality_check(min_lines=3)` rejects Tesseract results with zero or one line, so genuine image-only pages (e.g. the cover) get re-tried by Apple Vision, then Surya, before the final Surya result (empty) is accepted. Wastes a few seconds per image-only page but does not affect correctness.
- **Safety**: the original `results/boston_artifacts/` split is untouched; the cascade writes to a different directory because `doc_name` comes from `path.name` (`a_history_of_boston_in_50_artifacts`) rather than the custom-named `boston_artifacts` folder.

### A History of Boston in 50 Artifacts — Claude API run

- **Source**: same 209 spreads (418 half-pages, 1512×1642 px each) as above
- **Engine**: `ClaudeApiEngine(model="claude-sonnet-4-6", use_batch=True)` — 9 sub-batches of ≤50 images, polled with 60s base interval
- **Re-runs**: 33 Sonnet refusal pages re-run via `rerun_summary_pages.py` with `ClaudeApiEngine(model="claude-haiku-4-5-20251001", use_batch=False)` — all 33 fixed
- **Cost**: $1.69 Sonnet Batch + $0.09 Haiku real-time = **$1.78 total**
- **Assembly**: `assemble_boston_claude_api.py` — blank pages skipped, summary/refusal pages wrapped in HTML comments; output `results/boston_claude_api.orig/chapter_01_untitled.md`
- **Word count**: 53,548 words (vs 53,260 Surya — within 0.5%)
- **Split**: `doc2md split --artifacts --output-dir results/boston_claude_api` → **35 chapters** (3 named front matter, 5 PART intros removed, 24 artifact-level items, Conclusion, Appendix, Notes, Bibliography, Index)
- **Index linking**: `doc2md link-index results/boston_claude_api` → **396 links** (vs 403 Surya) across 388 unique terms (vs 387 Surya)
- **Quality vs Surya**: same word count; Claude outputs single-line index entries (665 lines) vs Surya's column-wrapped entries (917 lines); Claude correctly outputs 0 footnote definitions (no footnote text visible on Libby pages); Surya had 34 false `[^YEAR]:` definitions from bibliography entries

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
- ~~**Cascade image-only page over-escalation**~~ — fixed: `default_quality_check` now returns `True` for empty `raw_text`, short-circuiting at Tesseract for image-only pages
- **Cascade title-detection regression** — Tesseract and Apple Vision don't provide font metadata (block dicts), so their pages bypass `analysis/segmenter.py`'s font-based title/heading classification. Pages that would have been classified as headings via font size/name in a Surya-only run fall through to raw-text heuristics in the cascade run

## Vision-Model Alternatives for Screenshot Extraction

Evaluated as potential replacements for the OCR cascade (stages 2–6) on screenshot/scanned sources. Digital PDFs (Cambridge, papers) are unaffected — PyMuPDF remains optimal there.

### Qwen2.5-VL 7B (local, via Ollama/MLX)

- **Memory**: ~15–17 GB at Q4 on M3 Max (Ollama KV-cache bug inflates beyond weights-only ~4.4 GB); fits comfortably in 36 GB unified memory
- **Speed**: ~7–17 sec/page (vision encoder + text generation at ~30–50 tok/sec on M3 Max); Boston 418 pages → ~60–120 min via Ollama; ~30–60 min via MLX (~2× faster)
- **Thermal**: GPU/Metal path — comparable to Surya-on-MPS (which completed Morocco 103 pages in 16 min with zero throttling). CPU path not recommended.
- **Accuracy**: DocVQA 95.7%; purpose-built for structured document extraction. Strong on raw character-level OCR and multi-column layouts. Instruction-following on nuanced formatting (footnote vs caption, heading hierarchy) is weaker at 7B.
- **Pipeline simplification**: replaces OCR cascade + classifier (stages 2–5); assemble/output stages still needed

### Claude API (claude-sonnet-4-6, Batch API)

- **Speed**: ~2–4 sec/page real-time; Batch API (async, ≤24 hr) processes Boston 418 pp in ~90 min turnaround (submit-and-poll)
- **Thermal**: zero local compute; no thermal risk
- **Cost**: ~$0.004/page Sonnet real-time; **Batch API 50% discount** → Boston $1.69 Sonnet + $0.09 Haiku re-runs = **$1.78 total for 418 pages**
- **Accuracy**: frontier model; excellent heading-classified markdown in one pass; eliminates cascade + classifier stages. Minor issues: some narrative pages trigger copyright refusals (re-run with Haiku); Haiku hallucinates footnote definitions despite prompt instructions
- **Prompt**: verbatim transcription, headings via `#`/`##`/`###`, body word-for-word with hyphenation joining, footnote markers inline, footnote definitions only when visible on page, figure captions as blockquotes, omit page numbers/running headers
- **Implementation notes**: proxy workaround (use `HTTPS_PROXY` via `httpx.HTTPTransport`, not `ALL_PROXY` which requires `socksio`); chunked into ≤50 images per Batch API POST to avoid proxy size limits; `BATCH_THRESHOLD=10` (auto-batch >10 pages)
- **Constraints**: requires internet + API key; not local-first; image downscaling (0.5×, 0.75×) triggers copyright refusals on narrative pages — full resolution required

### Recommendation

| Criterion | Cascade (current) | Qwen2.5-VL | Claude API |
|---|---|---|---|
| Speed (Boston 418 pp) | ~7 min | ~60 min | ~90 min (batch) |
| Thermal risk | Low (GPU path) | Low (GPU path) | None |
| Cost | Free | Free | ~$1.78/book (Batch) |
| Accuracy (raw OCR) | Good | Very good | Very good |
| Structure output | Rule-based (regressions) | Prompt-based (weaker) | Prompt-based (strong) |
| Local-first | Yes | Yes | No |
| Pipeline stages replaced | 0 | 2–5 | 2–6 |

Best fit by use case: cascade for bulk re-processing where speed matters; Claude API for new books where cascade has known regressions (Morocco body chapters, Boston title detection) and cost is acceptable; Qwen2.5-VL not recommended given speed regression vs cascade and accuracy regression vs Claude API.

## Future Work: OCR Cascade

The cascade is functional end-to-end and already delivers a ~2.5× speedup on Boston, but several quality and performance improvements are identified and not yet implemented. Each is a self-contained follow-up.

### ~~1. Fix image-only page over-escalation~~ (done)

`default_quality_check()` now returns `True` when `raw_text` is empty — image-only pages short-circuit at the first engine.

### 2. Preserve Surya block metadata for classification

When a page is handled by Surya (either as a primary or fallback stage), its `rec_results[j].text_lines[k]` includes bbox and per-line confidence but doesn't currently feed `page.block_dicts`. Populating `block_dicts` from Surya's output would restore font-based classification for Surya-handled pages. For Tesseract/Apple Vision pages, the fix is harder — neither engine exposes font metadata cheaply. Options:

- **Accept the regression**: cascade-handled pages use raw-text heuristics; font-based classification only works when Surya is primary.
- **Detect headings statistically**: compute per-line height in the OCR output (all engines expose bboxes). Lines whose height is >1.2× the median body line height are likely headings. Tractable without engine-specific metadata.
- **Run Surya just for layout**: on every page, run Surya's cheaper `det_predictor` to get bbox sizes, then use a faster engine for recognition. Gives up some of the cascade speedup but preserves layout quality.

### 3. Calibrate confidence thresholds per engine

`default_quality_check(min_confidence=0.60)` uses the same threshold for all engines. Tesseract, Apple Vision, and Surya have different confidence distributions — Tesseract tends to report 70-95 for clean English, Apple Vision 0.85-0.99, Surya 0.90-0.99. A single 0.60 floor means the cascade under-utilizes Tesseract's discrimination. Per-engine thresholds calibrated on a labeled sample (e.g. 100 Boston pages with known correct output) would tighten the cascade.

### 4. Engine-specific column preprocessing defaults

Currently `build_default_cascade(folder)` runs `detect_column_bounds()` once and passes the same column list to both Tesseract and Apple Vision. Apple Vision handles multi-column layouts better than Tesseract (its built-in layout analysis is reasonable), so passing columns to Apple Vision may actually hurt accuracy by forcing it to process pre-split strips. Worth measuring; could skip column preprocessing for Apple Vision while keeping it for Tesseract.

### 5. Cache OCR output by content hash

The pipeline's cache currently records "extract" as a stage flag without storing the per-page text. Reprocessing a book re-runs OCR on every page even when the source screenshots are unchanged. Adding a per-image hash → cached `OcrResult` table would let iterative tuning (adjusting thresholds, re-running chapter splitter) happen without repeating the expensive OCR step. For Boston that means 7 min → <10 sec on reruns.

### 6. Cross-engine benchmark on a representative book set

Run the cascade on one book from each major category and record:
- Per-engine invocation counts (how many pages handled by each stage)
- Wall-clock time per stage
- A manual accuracy spot-check on 20 random pages per book
- Thermal behavior (pmset thermlog)

Candidate books: Boston (image-heavy Libby spreads), Morocco (text-heavy browser screenshots), Cambridge vol 1 (Arabic transliteration, math, non-Latin scripts), Wood at Midwinter (short story, clean single-column). This gives concrete evidence for tuning the default cascade configuration and for deciding which engines to offer out of the box.

## E-Book Reader (Implemented)

### Overview

Built-in web-based Markdown reader at `reader/`. No build step — vanilla JS + CSS, served via embedded `http.server` in the PyWebView desktop app. Paginated two-column layout inspired by Libby/Kindle.

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
- **Paper header** — YAML front matter stripped before rendering; title/authors/journal·year shown above chapter content
- **Citation hover popovers** — inline `[N]` references resolved against rendered `<ol>` reference list; hover shows citation text in popover
- **Figure click modals** — "Figure N" / "Fig. N" text references matched against `figures.json`; click opens fullscreen overlay with high-res figure image and caption
- **Papers in library** — `results/papers/` treated as a book; paper YAML metadata (title, authors, journal, year) included in library.json and displayed in reader

### Usage

```bash
python reader/build_library.py   # generate library.json
doc2md-reader                    # launch desktop app (PyWebView)
# or: python src/doc2md/desktop.py
# or for dev: python -m http.server 8000 → http://localhost:8000/reader/
```

### Future reader enhancements

- Full-text search across chapters
- Bookmarks and highlights (Web Selection API)
- Font family selector (serif/sans-serif/dyslexia-friendly)
- Line spacing and margin controls
- "Time left in chapter" estimate
- Offline support (Service Worker)
- ~~Desktop app wrapper~~ ✅ `doc2md-reader` — PyWebView desktop app (py2app alias bundle in `dist/`)

### Tech stack

| Component | Choice |
|---|---|
| Markdown→HTML | markdown-it + markdown-it-footnote (vendored in `reader/vendor/`) |
| Pagination | CSS multi-column layout + scrollLeft |
| Framework | Vanilla JS (~450 lines) |
| Themes | CSS custom properties |
| Serving | PyWebView + embedded `http.server` (desktop); `python -m http.server` (dev) |
| Desktop bundle | py2app alias mode — `dist/doc2md Reader.app` (~228 KB, symlinks into venv) |

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
2. **Section-level detection** — finds PART headers, named sections (Preface, Introduction, Notes, Bibliography, Index), titled sections (CONCLUSION, APPENDIX); handles wrapped multi-line titles and HTML tag stripping; all patterns accept optional `(?:#+\s*)?` prefix to handle markdown heading-prefixed lines from Claude API output
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

`parse_index_md()` handles main entries, sub-entries, `(cont.)` continuations, abbreviated page ranges (`516–17` → 516–517), "See also" cross-refs (plain and italic `*See also ...*`), wrapped continuation lines (detected by mid-sentence line endings), and bibliography spillover detection (stops at double blank lines or `[^YEAR]:` patterns).

`_split_term_and_refs()` strips markdown inline emphasis (`*N*` → `N`) before applying `_TRAILING_REFS_RE`, so italic illustration page refs (common in Claude API output) are extracted correctly. Returns clean (markdown-stripped) term for reliable chapter text matching.

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
| Boston Artifacts (Surya) | 1,666 | 85% | Pageless mode, 59 artifact-level chapters |
| Boston Artifacts (Claude API) | 396 | — | Pageless mode, 35 chapters; 388 unique terms linked |
| **Total** | **20,823** | | **7 of 8 clean** |

### Known issues

1. **V4 semicolon-delimited format** — v4's index `.orig.md` was corrupted by a previous buggy run (linked output was saved back as the original). The parser is now correct for new extractions; v4 needs re-extraction from the PDF to regenerate a clean index.

2. ~~**Years parsed as page numbers**~~ — fixed: `_filter_year_refs()` in `link_index` computes `max_page = max(ch.page_end for ch in chapters)` and moves refs exceeding that threshold back into the term text.

3. ~~**Italic page refs unlinked (pageless mode)**~~ — fixed: `_split_term_and_refs()` strips `*N*` markdown before `_TRAILING_REFS_RE`; pageless renderer no longer exits early on entries with empty `page_refs`; `*See also*` italic wrapper now recognized by the "See also" extractor.

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

## Academic Paper Pipeline (Implemented)

Ingests academic PDFs (e.g. Cell journal), converts to structured markdown, runs biomedical entity recognition, and generates a cross-paper entity index. Tested on Stuart et al. 2019 (Seurat v3, *Cell*).

### PDF extraction

**PyMuPDF remains the right tool for digital PDFs.** Cell papers are born-digital; PyMuPDF extracts text directly from PDF objects at ~0.12 sec/page with perfect fidelity. Marker and MinerU were evaluated as alternatives: both are 10–90× slower on digital PDFs (Marker uses PyMuPDF internally as its first step), and both show documented regressions on two-column journal layouts. Scanned content already has the Surya cascade. No change to the extraction layer is needed.

**Two-column layout**: PyMuPDF's `get_text("dict")` reads blocks in document order, which for two-column PDFs may interleave columns. Mitigation: use `sort=True` in `get_text()` to get spatial reading order, or detect column bounds via `chrome_cropper.detect_column_bounds()` (already implemented).

**GROBID** (not adopted) would add structured metadata extraction (authors, DOI, section headers in TEI/XML) but outputs XML rather than readable markdown, requires a running server, and is slower. Worth revisiting if reliable metadata extraction proves difficult with heuristics.

### NotebookLM evaluation

Evaluated and **rejected for this use case**. NotebookLM is a RAG chat interface: it answers questions across uploaded PDFs but cannot systematically extract entities, produces no machine-readable output (copy-paste only), and has no export beyond Google Sheets via the manual Data Tables feature. Hallucination rate ~13% makes it unsuitable for a structured index. No documented use case of systematic entity extraction from a paper corpus exists.

### Biomedical NER: PubTator 3.0 + BERN2 cascade

Two complementary tools; use in cascade:

**PubTator 3.0** (primary): NCBI's pre-computed annotation service covering 36M PubMed abstracts + 6M PMC full-text articles, updated weekly. Query by PMID → returns structured JSON/BioC with normalized entity IDs (NCBI Gene IDs, MeSH terms). ~67 seconds for 200 papers at the 3 req/sec rate limit. Entity types: genes, diseases, chemicals, variants, species, cell lines. F1: genes 84.6, variants 98.5, species 95.2. Nearly all Cell papers are PMC-indexed, so annotations are pre-computed. Known weakness: low precision in methods sections (complex protocols, abbreviations).

**BERN2** (fallback): processes arbitrary text via HTTP API or local install; ~55 min for 200 papers via API (use local install for bulk). Better than PubTator on diseases (F1 88.6 vs 79.2) and chemicals (92.8 vs 81.9). Covers 9 entity types vs PubTator's 6 (adds cell types, DNA/RNA). Use for papers not in PMC or to supplement PubTator on entity types it undershoots.

Neither tool handles experimental methods (CRISPR, ChIP-seq, etc.) well. **Regex layer implemented** (`papers/ner/methods.py`): 35-pattern vocabulary covering sequencing methods (scRNA-seq, ChIP-seq, ATAC-seq, CITE-seq, etc.), CRISPR variants (specific-before-general ordering), spatial transcriptomics (Visium, seqFISH, STARmap), RNAi, flow cytometry, and computational methods (UMAP, t-SNE, PCA, CCA). Runs on abstract/introduction/methods/results sections; skips references/discussion. Ollama hook for complex protocol extraction is future work.

### Cross-paper entity index

Once entities are normalized to canonical IDs (NCBI Gene ID, MeSH CUI), cross-paper indexing is a **simple inverted index**: `{entity_id → [{paper, section, context}]}`. Normalization — the hard part — is already done by PubTator/BERN2. Implementation is ~1–2 weeks of Python/SQLite. Phase 1 output: `entity_index.json` + `entity_index.md` per corpus.

**GraphRAG and LlamaIndex KnowledgeGraphIndex** were evaluated. Both add *relationship extraction* (subject-verb-object triples via LLM calls), not entity identification. GraphRAG costs ~$10–20 in LLM API calls for 200 papers and adds 3–4 weeks of engineering. The payoff is multi-hop relational queries ("genes that activate a protein in Cell Line X") vs. co-occurrence queries ("papers mentioning Gene X"). For Phase 1 the simple inverted index covers the stated need; graph extraction is a natural Phase 2.

### Proposed pipeline

```
PDF → PyMuPDF extract → clean/segment (paper sections) → PMID lookup → PubTator annotations
                                                        ↘ (not in PMC) → BERN2 on raw text
→ merge + normalize entities → inverted index → entity_index.json + entity_index.md
```

### Implemented pipeline stages

```
doc2md papers process <pdf>          # full pipeline: extract → clean → segment → NER → markdown + entities.json + entity_index
```

Stages: PyMuPDF extract → two-column reflow → normalize ligatures → strip watermarks/symbols → header/footer removal → classify blocks → detect chapters → section labelling → link footnotes/citations → merge text → write markdown → enrich metadata → NER (PubTator + BERN2) → write entities.json → update entity_index.json + entity_index.md → figure extraction.

**Metadata enrichment** (`papers/metadata.py`): four-source cascade (PDF metadata → first-page font heuristics → PubMed efetch XML → CrossRef REST API), each source only fills empty fields.

**Figure extraction** (`papers/figure_extractor.py`): raster images via `get_images(full=True)` + `extract_image(xref)` (skip < 150px); vector fallback via `get_pixmap(clip=bbox)` on type-1 image blocks; caption matched as nearest text block starting with "Figure"/"Fig." within 150pt. Per-page deduplication: when multiple images share the same caption ID, the largest (by area) wins; uncaptioned subpanels are dropped when any captioned figure exists on the page (kept with fallback IDs `p{page}i{idx}` only on fully uncaptioned pages). Saves to `output_dir/figures/` with `figures.json` index.

**Preprint watermark filter**: strips bioRxiv/medRxiv CC-BY notices from `raw_text` (cleaner) and from block dicts (segmenter). Also strips symbol-only lines (U+25CF ●, U+2022 •, etc.) that are PDF encoding artifacts from data tables/figures — both in `strip_preprint_watermarks()` and in `_is_boilerplate()`.

**Figure panel label filter**: single-letter or N/M fraction blocks (e.g. "A", "2/24") detected by `_is_figure_panel_label()` and dropped before heading classification. **Math expression filter** (`_is_math_expression()`): blocks containing `=`, `−`, `ˆ`, `˜`, or Unicode Greek/math symbols are dropped — applied to the large-font, heading-font, AND all-caps branches. Equations like `C = BW T` and `I = N` pass `_is_all_caps_heading()` because all their letters happen to be uppercase; the math filter now catches these in all three branches.

### Processing log: Stuart et al. 2019 (Seurat v3)

- **Source**: bioRxiv preprint PDF downloaded from bioRxiv (`10.1101/460147`), 24 pages, 19 MB
- **Extraction**: PyMuPDF, all 24 pages have block_dicts; two-column reflow applied
- **NER**: PubTator (PMID 31178118) + regex method extractor (147 method entities: scRNA-seq, ATAC-seq, CITE-seq, STARmap, UMAP, CCA, etc.); BERN2 public API down at test time
- **Figures**: 8 extracted — Figures 1, 2, 4, 5 captioned; page 6 has 4 unlabeled subpanels (fallback IDs p6i0–p6i3, likely Figure 3 panels)
- **Headings fixed**: `C = BW T` and `I = N` (Methods equations) were misclassified as headings via the ALL_CAPS branch; fixed by adding `_is_math_expression()` guard there
- **Runtime**: ~21 sec (network-bound by PubTator lookup; local extraction ~3 sec)

### Known paper pipeline issues (found via Playwright e-reader audit)

1. **Superscripts as footnote refs** — author affiliation numbers (`[^1]`, `[^2]`), citation superscripts, and subscript gene names (`CD[^4]`, `Gad[^2]`) are all emitted as `[^N]` markdown footnote syntax. The reader renders these as 321 footnote links against only ~5 actual definitions. Root cause: superscript spans in PyMuPDF are not distinguished from true footnote markers during extraction; need a heuristic to suppress mid-line superscripts that are citation/affiliation numbers.

2. **Figure refs not clickable** — 31 "Figure N" text references appear in the markdown, but none are wired to the figure modal in the reader. The modal only activates for images embedded inline; text refs need to be converted to `<span data-fig="N">Figure N</span>` anchors during rendering.

3. **`Reference`/`Query` diagram labels as headings** — these single-word figure-axis labels appear as `### Reference` / `### Query` throughout the Results section. They cannot be filtered by `_is_math_expression` or `_is_figure_panel_label`; suppressing them requires page-level figure detection (e.g. skip heading classification for blocks that overlap with an image bounding box).

4. **Library card title** — the papers folder shows `"Papers1 chapters"` (no separator between title span and chapter-count span). Reader `build_library.py` uses the results subfolder name (`papers`) as the book title; should use the YAML `title` field from the first chapter's front matter instead.

5. **Topbar shows folder name** — reader topbar displays `"Papers"` instead of the paper's actual title. Same root cause as #4.

6. **Author metadata parsing** — affiliation superscripts (`1`, `2`, `*`) are extracted as separate list items in the YAML `authors` field. The metadata extractor needs to strip trailing superscript tokens from author name strings.

7. **Garbled table text** — comparison table cells produce `"80$3B"` artifacts (PDF encoding of method name abbreviations). Not caught by the preprint watermark filter; needs a separate table-cell artifact filter or a minimum word-length heuristic.

## Non-Goals (Current Scope)

- Cloud LLM support (currently Ollama-only)
- Table extraction / reconstruction
- Multi-language OCR
- Intermediate data persistence (pages are re-extracted on partial resume)
