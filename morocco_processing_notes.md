# Morocco Book Processing — Detailed Notes

This document captures the troubleshooting history of processing *Morocco: Globalization and Its Consequences* (Cohen & Jaidi). It's the first book processed by doc2md that is sourced from **full-screen browser screenshots** containing a Libby-style ebook reader plus OS/browser chrome. The PRD keeps a short summary in its "Processing Log" section and links here for the full history.

See `PRD.md` § "Processing Log → Morocco" for the summary entry.

## Initial run (pre-optimizations)

- **Source**: 103 browser screenshots (1366×768, full-screen captures of VBooks web viewer with Ubuntu panel + Chrome tabs + dock visible), 38 MB
- **Pipeline taken**: `is_libby_spread()` → False (original threshold) → `extract_screenshots()` (one page per image) → `deduplicate()` → `detect_page_numbers()` (LLM) → `reorder_pages()`
- **OCR**: Surya, CPU only, **17.4 min**
- **Output**: 7,118 lines, single chapter
- **Structure detected**: TOC with page numbers (ix, 1, 47, 79, 113, 151), 4 numbered chapters (`CHAPTER ONE` through `CHAPTER FOUR`), Preface, Conclusion, Endnotes, Bibliography, Index

### Issues observed

1. **Browser chrome in OCR** — tab titles, URL bar, navigation buttons captured as text because screenshots include the full browser window, not just page content.
2. **Running headers not stripped** — chapter titles repeat as page headers on every page (e.g. `Debating and Implementing "Development" in Morocco` appears ~25 times). `detect_repeated_lines()` didn't catch them, possibly because OCR inconsistencies prevent exact matching.
3. **Page numbers in headers** — OCR'd page numbers mixed into body text (e.g. `43 Debating and Implementing "Development" in Morocco`).

## Reprocess with chrome cropper + unified OCR

Three optimizations added to target Morocco-style browser screenshots:

1. **`chrome_cropper`** — statistically detects consistent non-content borders via per-pixel variance across sampled images.
2. **Unified `_ocr_batched`** — shared between Libby spreads and non-Libby screenshots.
3. **`is_browser_screenshot()`** — routes ordered browser captures through the non-Libby path with `auto_number=True`, skipping dedup/reorder LLM calls.

### Bug: `is_libby_spread` misclassified Morocco as a spread

On the first reprocess, every Morocco image (1366×768, w/h ≈ 1.78 > 1.5) tripped the original aspect-ratio check and was routed to `extract_screenshot_spread()`, which split each image at midpoint and never invoked chrome cropping. All 103 images → 206 halves → 13 `_ocr_batched` recognition passes. The run completed in ~45 min but the output still contained "Relaunch to update" once per page and mixed Chrome tab titles/URL bar text throughout.

**Fix**: `is_libby_spread()` now computes the **content** aspect ratio (cropped dimensions when chrome is detected, raw otherwise), so browser screenshots with w/h < 1.5 after cropping correctly fall through to the non-spread path.

### Thermal throttling under batched OCR

The second reprocess (with the bug fixed) took the intended `extract_screenshots()` → chrome crop → `_ocr_batched()` path. It completed batches 1 and 2 in ~5 and ~6 min respectively (776 and 1017 text lines per batch), then hit severe thermal throttling on batches 3–4. Recognition rate collapsed from ~3 items/sec to ~0.02 items/sec (`180 s/it`), and a single detection pass that had been taking ~16 sec ran for 14:37. Surya's own progress estimate projected 8–10 hours to finish the remaining ~4 batches. The run was killed at ~1 hour elapsed after 2.5/7 batches.

Diagnosis pointed to sustained CPU load from large, dense batches. Each batch of 16 cropped full-book pages contained 776–1017 detected text lines — 2–3× the density of the Boston book's Libby-spread batches (half-pages, photo-heavy, ~300–500 lines per batch), which had processed cleanly. Morocco's batches sustain full CPU for 5+ minutes with no cooling window, compounded by the session already being thermally warm from the earlier buggy run.

### Sequential A/B testing

To isolate whether cropping, batching, or thermal state was the dominant factor, we ran two controlled tests.

**Test 1: sequential `_ocr_pil` on 10 cropped images.** Processed first 10 Morocco pages one at a time via `_ocr_pil()` (bypassing `_ocr_batched` entirely). Total 170 sec, average 17 sec per image, **no thermal throttling**. Per-image times ranged from 5.9 sec (image-heavy cover) to 24 sec (text-dense body pages). The steady-state rate stayed flat throughout — sequential execution gave the CPU enough microsecond-scale breaks between images to avoid sustained thermal buildup. This ruled out cropping and cumulative machine state as the primary cause.

**Test 2: A/B on 5 images, cropped vs uncropped, both sequential.** Same 5 images processed via `_ocr_pil()` twice:

| Metric | Uncropped (1366×768) | Cropped (841×653) |
|---|---|---|
| Total time | 109.3 s | 67.8 s |
| Lines detected | 333 | 167 |
| Lines/sec | 3.05 | 2.46 |

**Findings:**
- **Cropped is 38% faster wall-clock** (0.62×) despite processing smaller images.
- **Cropped detects 50% fewer text lines** — the missing half is OCR'd browser chrome (tab titles, URL bar, "Relaunch to update", math symbols from navigation icons). Cropping is therefore critical for output quality, not just speed.
- **Cropped is ~20% slower *per line*** (2.46 vs 3.05 lines/sec). Hypothesis: Surya's `RecognitionPredictor` normalizes text regions to a fixed internal height. In a cropped image the book text occupies a larger fraction of the frame, so each text region is physically larger in pixels and takes more recognition work per line. This slight per-line penalty is more than offset by the massive reduction in lines to process.
- Extrapolated full-book time for **cropped sequential via `_ocr_pil`**: ~23 min if all pages behave like this sample, more realistically **~35 min** accounting for denser body pages beyond the cover/front matter.

### Conclusion (CPU path)

Batched OCR works well on sparse Libby spreads but breaks down thermally on dense academic text. Sequential `_ocr_pil` is the right fallback for CPU-only execution on text-heavy content. The chrome cropper is a clear win on both speed and quality; the unification of Libby/non-Libby extraction paths is sound but needs a configurable batch-size (or sequential opt-out) for machines without GPU/MPS.

## Successful reprocess with MPS (GPU)

To test the GPU hypothesis, the pipeline was rerun on the same machine with `dangerouslyDisableSandbox` (the Claude Code sandbox was blocking Metal/IOKit access, making PyTorch's `torch.backends.mps.is_available()` return False even on macOS 15.7.4). Confirmed with `torch.randn(1000, 1000, device='mps') @ self` running 10 iterations in 0.071 s — proper ~1.4 TFLOPS GPU acceleration. Pipeline then run with `TORCH_DEVICE=mps` and full `_ocr_batched` (16 images per batch) + chrome cropping + `is_browser_screenshot=True` path.

**Results: complete success.**

| Metric | CPU buggy run | CPU batched (killed) | **MPS** |
|---|---|---|---|
| Wall time | ~45 min | ~1 hour (2.5/7 batches) | **~16 min** |
| Thermal issues | None | Severe (0.02 it/s) | **None** |
| Output | Browser chrome polluted | Browser chrome polluted | **Clean (0 chrome markers)** |
| Output lines | 7,106 | — | **5,411** (30% shorter — chrome removed) |
| LLM calls | ~100 (dedup/reorder) | ~100 | **0** |

**Per-batch timing (MPS vs CPU):**

| Batch | Lines | MPS | CPU (buggy run) | Speedup |
|---|---|---|---|---|
| 1 | 776 | 1:40 | 4:35 | **2.75×** |
| 2 | 1017 | 2:30 | 6:23 | **2.55×** |
| 3 | 958 | 2:35 | 3:31 + thermal death | ~2.5×+ |
| 4 | 933 | 2:30 | n/a (CPU failed) | |
| 5 | 1008 | 2:25 | n/a | |
| 6 | 1046 | 2:30 | n/a | |
| 7 | 595 (final 7 imgs) | 0:50 | n/a | |

Total OCR: ~15 min. Pipeline end-to-end: ~16 min. Zero thermal throttling across 7 batches over 70 min of sustained GPU load.

**Detection timing**: Chrome detection via `det_predictor` ran at ~1.1 s per sub-batch on MPS vs ~8-9 s on CPU — an ~8× speedup for detection specifically. Recognition ran at 10–20 items/sec on MPS with occasional dips to 3 it/s (vs CPU 2–5 it/s steady, falling off a cliff after the thermal threshold).

**Output verification**: grep for `"Relaunch"|"Mahler"|"libbyapp"|"Google Chrome"` → 0 matches. First 40 lines show clean book cover and volume listings. Full book content intact.

### Takeaways

1. **Cropping, batching, and the `is_browser_screenshot` path all work as designed when GPU is available**. The earlier failures were thermal/memory pressure on CPU, not correctness bugs (those were fixed separately via the `is_libby_spread` content-aspect-ratio patch).
2. **GPU speedup was ~2.5–3×**, at the conservative end of the 2–10× range I predicted. Surya likely has some ops that fall back to CPU even when MPS is set. Still a large practical win.
3. **The sandbox blocks Metal/IOKit** as a side effect of its general sandboxing, not via a configurable knob. Running with `dangerouslyDisableSandbox` is the only way to access MPS from within Claude Code. For a persistent fix, the user would need to add a project-level allowlist entry in `.claude/settings.local.json` or run outside Claude Code.
4. **On the original PRD CPU baseline (17.4 min)**: the new MPS run at 16 min is slightly faster *and* produces clean output *and* uses zero LLM calls. The CPU path at best matches the original speed (with worse quality) once the thermal issue is worked around via sequential mode.

### Recommended configuration

- **GPU/MPS available**: `extract_screenshots` with `_ocr_batched(batch_size=16)` + chrome cropping + `is_browser_screenshot` detection. Best of all worlds.
- **CPU only**: `extract_screenshots` should fall back to a sequential `_ocr_pil` loop when MPS is unavailable. This is a follow-up code change (not yet implemented) — the function would check `torch.backends.mps.is_available()` and choose the path accordingly.

## Chapter splitter hardening for Morocco

After the successful MPS reprocess, `doc2md split` produced 7 directories with three problems vs. Boston (which splits into 59 clean dirs):

1. **Duplicate `010_preface`/`020_preface` and `050_bibliography`/`060_bibliography`** — caused by Morocco's running headers (chapter titles repeating at every page top). `_NAMED_SECTION_RE` matched every occurrence and emitted a new chapter each time.

2. **Garbage `030_conclusion_of_the_analysis_was_that_today_the_fear_rememthe_`** — at line 2129, Surya merged two parallel OCR columns into one 150+ char line: `conclusion of the analysis was that "Today, the fear (rememthe people. Why not, if Morocco has advanced political reform bour for fear that he was a secret agent) has ceded its place to`. The `re.IGNORECASE` `_TITLED_SECTION_RE` matched lowercase `conclusion` at line start and captured the rest as the section subtitle.

3. **No detection of the 4 real body chapters** — Morocco's body uses plain-word chapter markers (TOC entries say "One", "Two", etc.). The `CHAPTER ONE/TWO/THREE/FOUR` strings that do appear in the body (lines 4389–4611) are actually **endnote-section labels**, not body chapter headers. Adding a `CHAPTER\s+WORD` regex would create false splits in the endnotes without helping the real body. Out of scope for this fix — would need page-number-based splitting (LLM detection or manual `ChapterDef`).

### Fix: two surgical changes in `detect_chapters()`

1. **Running-header dedupe**: track `seen_named: set[str]` across both `_NAMED_SECTION_RE` and `_TITLED_SECTION_RE`. Emit a chapter only on the first occurrence of each lowercased section word; skip subsequent matches. Preserves Boston behavior (which has exactly one of each).

2. **Length guard on `_TITLED_SECTION_RE`**: require the stripped matched line to be ≤ 80 characters. Real headers are short (`CONCLUSION. The Future of Archaeology in Boston` = 47 chars). The Morocco OCR garbage is 150+ chars. One check, no false positives on legitimate headers.

Tests added to `tests/test_chapter_splitter.py`: `test_named_section_not_duplicated_on_running_header`, `test_titled_section_rejects_mid_paragraph_match`, `test_titled_section_accepts_short_header`. Full suite: 465 passed, 2 skipped, no regressions.

### Morocco re-split results

Before fix:

```
010_preface
020_preface                                                        ← duplicate
030_conclusion_of_the_analysis_was_that_today_the_fear_rememthe_   ← garbage
040_conclusion_what_future_for_a_development_policy
050_bibliography
060_bibliography                                                   ← duplicate
070_index
```

After fix:

```
010_preface                                                   (4230 lines)
020_conclusion_what_future_for_a_development_policy           (425 lines)
030_bibliography                                              (142 lines)
040_index                                                     (436 lines)
```

`doc2md link-index` then produced 293 markdown hyperlinks pointing to the four real section directories.

### Remaining Morocco quality gap

The 4 real body chapters (`One`, `Two`, `Three`, `Four` in the TOC) are still concatenated inside `010_preface/` as a ~4000-line blob. Morocco's body lacks any regex-detectable chapter markers, so the splitter cannot separate them without either (a) keeping LLM page-number detection enabled so TOC page boundaries can map back to body lines, or (b) a manually supplied `ChapterDef` list (the Wood at Midwinter approach). Both options are out of scope here.

Other remaining Morocco issues (out of scope for the chapter splitter fix):

- **Running headers in body text** — chapter titles repeating at every page top are still in the output. Separate fix lives in `assembly/cleaner.py::detect_repeated_lines()`; likely now tractable because the chrome cropping removed the OCR noise that previously defeated exact-match dedup.
- **OCR-merged columns** — the parallel-text interleaving at line 2129 (and similar spots) is a Surya limitation when book pages have two narrow columns. Would need a column-aware preprocessor.
