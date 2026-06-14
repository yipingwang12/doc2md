# Processing Log

Per-book run history, quality stats, and library-scale strategy.
See [PRD.md](../PRD.md) for pipeline overview and [OCR_ENGINES.md](OCR_ENGINES.md) for engine details.

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
- **Full history** (bugs, thermal issues, A/B tests, MPS setup, chapter splitter hardening): see [`morocco_processing_notes.md`](../morocco_processing_notes.md)

#### Claude API run (Sonnet Batch + --rerun-empty)

- **Run**: `run_claude_api_ocr.py synced/morocco_globalization_and_its_consequences --book morocco` → 3 sub-batches of 50, $0.36, ~2.2 min wall-clock
- **Copyright refusals**: 68% of pages (70/103) refused or hard-blocked — 8 hard API errors, 62 soft refusals (summary text). Root cause: recently published academic monograph recognised by model. `--rerun-empty` fixed 10/18 hard-blocked pages via Haiku; soft refusals required manual grep-and-zero sweep with multiple pattern passes.
- **Usable output**: 33/103 pages (32%) with real content — front matter, partial chapter text, Endnotes, Bibliography, Index
- **Chapter splitting**: not completed due to refusal rate making output too sparse. Prompt fix applied (`do NOT output column label or separator`) and chapter splitter extended with `_CHAPTER_RE` for use when re-run with a less restrictive model.

## Library Scale & Processing Strategy

### Inventory (as of May 2026)

- **Location**: `gdrive:listening/books` (rclone remote)
- **Books**: 149 folders
- **Screenshots**: ~47,000 image files total
- **Effective pages**: ~80,000 (Libby spreads counted as 2 pages each; estimated 70% Libby / 30% browser screenshots)
- **Formats**: mix of Libby landscape spreads (auto-detected by `is_libby_spread()`) and browser screenshots (chrome-cropped via `detect_content_bounds()`)

### Per-book cost benchmarks

| Book | Pages | Engine | Cost | Notes |
|---|---|---|---|---|
| Boston (Libby spreads) | 418 | Sonnet Batch | $1.78 | ~$0.004/page; near-zero refusals |
| Morocco globalization (browser) | 103 | Sonnet Batch | $0.36 | ~$0.004/page; 68% refusal rate |

### Cost estimate for full library (80,000 pages)

| Engine | Config | Cost | Wall time |
|---|---|---|---|
| Anthropic Sonnet Batch | — | ~$320 | ~few hrs (Anthropic-parallel) |
| Anthropic cascade (Haiku→Sonnet) | — | ~$120 | ~few hrs |
| Qwen2.5-VL-7B | 10× RunPod A10G spot | ~**$25–35** | ~15 hrs |
| Qwen2.5-VL-7B | 1× RunPod A10G | ~**$25–35** | ~150 hrs |

Note: Anthropic cost assumes low refusal rate (Boston-like). If refusal rate across library resembles Morocco (~68%), effective cost per usable page rises significantly.

### Copyright refusal risk by book type

Refusal rate depends on how recognisable and recently published the book is to the model. Boston (local history, archaeology) had near-zero refusals; Morocco globalization (2007 academic monograph, politically sensitive topics) had 68%. Likely risk factors: recent publication date, well-known academic press, narrative-dense prose chapters. Endnotes, bibliographies, and indexes consistently transcribed without refusal across both books.

**Mitigation options**:
1. `--rerun-empty` with Haiku — catches hard-blocked pages; Haiku slightly less restrictive than Sonnet
2. Haiku→Sonnet cascade (`--cascade`) — quality gate via `_SUMMARY_RE` catches soft refusals before writing
3. Open-source model on cloud GPU — eliminates refusals entirely at ~$25–35 for full library
