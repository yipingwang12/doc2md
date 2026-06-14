# OCR Engines

Technical reference for the OCR cascade and vision-model alternatives.
See [PRD.md](../PRD.md) for pipeline overview and engine selection guidance.

## Engine Abstraction

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

## Available Engines

| Engine | File | Strengths | Weaknesses | Dep |
|---|---|---|---|---|
| `TesseractEngine` | `ocr_engines/tesseract.py` | Fastest on CPU (~0.2 sec/half-page on Boston); lightest thermal footprint; good on clean English | Poor on math, non-Latin scripts, complex layouts; no block metadata | `pytesseract` + `tesseract` binary |
| `AppleVisionEngine` | `ocr_engines/apple_vision.py` | Fast on Apple Silicon Neural Engine; no GPU contention; handles layout automatically | macOS only; weaker on math/unusual fonts | `ocrmac` (macOS only) |
| `SuryaEngine` | `ocr_engines/surya.py` | Most capable on math, non-Latin scripts, unusual layouts; provides rich block metadata that powers font-based classification | Slowest; thermal-stress under sustained CPU load; best with GPU/MPS | `surya-ocr` (core dep) |
| `ClaudeApiEngine` | `ocr_engines/claude_api.py` | Frontier model; structure-preserving markdown in one pass; zero local compute; no thermal risk | Requires internet + API key; ~$0.003–0.004/page at Sonnet pricing; copyright refusals on some narrative pages; Haiku hallucinates footnote defs | `anthropic`, `httpx` |
| `CascadeEngine` | `ocr_engines/cascade.py` | Runs multiple engines in order with per-page quality gating — only escalates to the next engine on pages that fail the check | — | n/a |

## Default Cascade

`build_default_cascade(folder=None)` builds a **Tesseract → Apple Vision → Surya** cascade, dynamically including only the stages whose Python dependency is importable. Surya is always the final unconditional fallback (it's a core dep). Column preprocessing (from `chrome_cropper.detect_column_bounds()`) is applied to Tesseract and Apple Vision stages when the folder has multi-column layout; Surya runs on full content pages.

```python
CascadeEngine([
    (TesseractEngine(columns=cols, lang="eng"), default_quality_check),
    (AppleVisionEngine(columns=cols), default_quality_check),
    (SuryaEngine(), None),  # final stage, accepted unconditionally
])
```

## Per-Page Quality Check

`default_quality_check()` rejects a result (triggering fallback to the next stage) if:
1. Mean confidence < `min_confidence` (default 0.60)
2. Line count < `min_lines` (default 3)
3. Non-printable character ratio > 0.30

Each stage runs on all items first, then the cascade re-runs failed items through the next stage. Page numbering (`auto_number=True`) is applied at the very end so page numbers stay sequential regardless of which engine produced each page.

## Wiring

`extract_screenshots(folder)` and `extract_screenshot_spread(folder)` default to `build_default_cascade(folder)` and `build_default_cascade()` respectively (the latter skips column detection because Libby spread halves are already single-column). Both accept an optional `engine` kwarg so tests and benchmarks can bypass the cascade with a bare `SuryaEngine()` or a mock.

## Vision-Model Alternatives

Evaluated as potential replacements for the OCR cascade (stages 2–6) on screenshot/scanned sources. Digital PDFs (Cambridge, papers) are unaffected — PyMuPDF remains optimal there.

### Qwen2.5-VL 7B (local, via Ollama/MLX)

- **Memory**: ~15–17 GB at Q4 on M3 Max (Ollama KV-cache bug inflates beyond weights-only ~4.4 GB); fits comfortably in 36 GB unified memory
- **Speed**: ~7–17 sec/page (vision encoder + text generation at ~30–50 tok/sec on M3 Max); Boston 418 pages → ~60–120 min via Ollama; ~30–60 min via MLX (~2× faster)
- **Thermal**: GPU/Metal path — comparable to Surya-on-MPS (which completed Morocco 103 pages in 16 min with zero throttling). CPU path not recommended.
- **Accuracy**: DocVQA 95.7%; purpose-built for structured document extraction. Strong on raw character-level OCR and multi-column layouts. Instruction-following on nuanced formatting (footnote vs caption, heading hierarchy) is weaker at 7B.
- **Pipeline simplification**: replaces OCR cascade + classifier (stages 2–5); assemble/output stages still needed

### Qwen2.5-VL on Cloud GPU (evaluated, not yet implemented)

Evaluated as an alternative to Anthropic API for library-scale processing, motivated by copyright refusal rates on academic texts.

- **Model**: Qwen2.5-VL-7B — smallest size with reliable structure-preserving OCR. 3B degrades on two-column layouts and footnote formatting. 32B requires multi-GPU.
- **Hardware fit**: ~14 GB float16; fits on T4 (16 GB) with INT8 quantisation or A10G/L4 (24 GB) comfortably
- **Speed**: ~0.12–0.2 pages/sec on single A10G; 80,000-page library at 10 parallel instances ≈ 15 hrs wall-clock
- **Copyright refusals**: essentially zero — self-hosted models have no content filtering layer; eliminates the primary failure mode of the Anthropic API for academic texts
- **Accuracy**: roughly equivalent to Haiku cascade results; weaker than Sonnet on heading hierarchy, footnote placement, and two-column ordering; potentially stronger than Claude on non-Latin scripts (Arabic transliteration) due to Qwen's multilingual document training
- **Western alternatives**: no Western open-source model clearly matches Qwen2.5-VL-7B on document OCR at 7B scale as of mid-2025. Closest options: Pixtral-12B (Mistral, French) — best Western substitute, similar hardware requirements, ~10–15% accuracy gap on structured academic text; Llama 3.2 Vision 11B (Meta) — weaker on document structure; PaliGemma 2 10B (Google DeepMind) — competitive on some document benchmarks; Phi-4-multimodal (Microsoft) — promising but less proven on long-form book transcription
- **Infrastructure**: vLLM or simple `transformers` inference loop; SQS or similar queue for page dispatch; per-page `.txt` checkpointing (already in pipeline) makes spot-instance interruption safe

#### Cloud Provider Comparison

| Provider | Instance | VRAM | On-demand | Spot/Preemptible | Notes |
|---|---|---|---|---|---|
| AWS | g5.xlarge | A10G 24 GB | ~$1.00/hr | ~$0.33/hr | Most availability |
| GCP | g2-standard-4 | L4 24 GB | ~$0.70/hr | ~$0.22/hr | Auto sustained-use discount |
| Azure | NVads A10 v5 | A10 24 GB | ~$0.90/hr | ~$0.15/hr | Patchier spot availability |
| **RunPod Secure** | A10G | 24 GB | **~$0.49/hr** | — | Proper datacenter; recommended |
| **Lambda Labs** | A10G | 24 GB | **~$0.60/hr** | — | Pre-installed PyTorch/CUDA |
| Vast.ai | varies | varies | **~$0.25–0.35/hr** | — | Marketplace; highest failure risk |

AWS/GCP/Azure are within ~10–20% of each other for equivalent hardware — not a meaningful differentiator. Specialist ML clouds (RunPod, Lambda Labs) offer 30–50% savings with adequate reliability for a one-off job. Vast.ai is cheapest but requires robust checkpointing due to node instability and has weak data privacy guarantees (third-party hardware).

**Why specialist clouds are cheaper**: stripped overhead (no compliance certifications, no enterprise SLAs, no multi-service ecosystem), leaner operations focused on GPU time only, opportunistic hardware sourcing. RunPod has two tiers: Secure Cloud (real datacenters, recommended) and Community Cloud (distributed third-party nodes, cheaper but privacy concerns). Lambda Labs runs its own datacenters and is the most reliable of the three.

### Claude API (claude-sonnet-4-6, Batch API)

- **Speed**: ~2–4 sec/page real-time; Batch API (async, ≤24 hr) processes Boston 418 pp in ~90 min turnaround (submit-and-poll)
- **Thermal**: zero local compute; no thermal risk
- **Cost**: ~$0.004/page Sonnet real-time; **Batch API 50% discount** → Boston $1.69 Sonnet + $0.09 Haiku re-runs = **$1.78 total for 418 pages**
- **Accuracy**: frontier model; excellent heading-classified markdown in one pass; eliminates cascade + classifier stages. Minor issues: some narrative pages trigger copyright refusals (re-run with Haiku); Haiku hallucinates footnote definitions despite prompt instructions
- **Copyright refusals**: two failure modes — (a) `type=errored` hard API block (400 "Output blocked by content filtering policy"); (b) soft refusal where model returns summary text instead of transcription. `--rerun-empty` re-runs 0-byte pages via Haiku real-time. `_SUMMARY_RE` quality gate catches both patterns. Morocco globalization had ~68% refusal rate (recent academic monograph); Boston had near-zero. Refusal rate is book-dependent.
- **Prompt**: verbatim transcription, headings via `#`/`##`/`###`, body word-for-word with hyphenation joining, footnote markers inline, footnote definitions only when visible on page, figure captions as blockquotes, omit page numbers/running headers. Book-specific extras in `prompts.py` (`--book KEY`). Morocco extra: two-column left-first (no column labels), omit running headers, chapter title pages, endnote markers. Boston extra: PART/artifact headings, Notes footnote defs, italic index page refs.
- **Implementation notes**: proxy workaround (use `HTTPS_PROXY` via `httpx.HTTPTransport`, not `ALL_PROXY` which requires `socksio`); chunked into ≤50 images per Batch API POST to avoid proxy size limits; `BATCH_THRESHOLD=10` (auto-batch >10 pages)
- **Constraints**: requires internet + API key; not local-first; image downscaling (0.5×, 0.75×) triggers copyright refusals on narrative pages — full resolution required

### NotebookLM (evaluated, not suitable for pipeline)

- **Input**: does not accept raw image files (PNG/JPG); requires PDFs, Google Docs, URLs, or audio. Image-based PDFs trigger Google's OCR backend — quality decent for clean text, variable for complex layouts.
- **Copyright**: no model-level refusals; uploads copyrighted content to Google's servers (ToS question, not technically enforced).
- **Q&A and summarization**: strong for interactive research — "what does this book say about X?", thematic connections across chapters, study guides, FAQs. Not suitable for producing structured output (no JSON, no chapter-linked index entries, no systematic entity extraction).
- **Scale**: ~50-source limit per notebook, no programmatic API — bulk processing 149 books not feasible.
- **Verdict**: useful complement for deep-diving into individual books interactively; not a replacement for the doc2md pipeline.

### Recommendation

| Criterion | Cascade (current) | Qwen2.5-VL | Claude API |
|---|---|---|---|
| Speed (Boston 418 pp) | ~7 min | ~60 min | ~90 min (batch) |
| Thermal risk | Low (GPU path) | Low (GPU path) | None |
| Cost | Free | Free | ~$1.78/book (Batch) |
| Accuracy (raw OCR) | Good | Very good | Very good |
| Structure output | Rule-based (regressions) | Prompt-based (weaker) | Prompt-based (strong) |
| Local-first | Yes | Yes | No |
| Copyright refusals | None | None | Book-dependent |
| Pipeline stages replaced | 0 | 2–5 | 2–6 |

Best fit by use case: cascade for bulk re-processing where speed matters; Claude API for new books where cascade has known regressions (Morocco body chapters, Boston title detection) and cost is acceptable; Qwen2.5-VL cloud for library-scale processing where copyright refusals are a concern (~$25–35 for full library vs ~$120–320 via Anthropic).

## Future Work

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
