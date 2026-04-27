"""Claude API vision OCR engine.

Sends page images to claude-sonnet-4-6 and asks for structure-preserving
Markdown. Unlike rule-based engines, Claude can output heading-classified
text in a single pass, potentially skipping the classify and
chapter-detection stages.

Confidence is always 1.0 (Claude does not report per-line scores); the
cascade quality check uses line_count instead for image-only detection.

Batch API mode is used automatically when len(items) > BATCH_THRESHOLD (10).
It submits all requests at once and polls with exponential backoff (60s base),
returning results in the original order. Cost is 50% lower than real-time.

Two-model cascade (ocr_batch_cascade):
  Run all pages through a cheap primary model (default: Haiku); re-run
  failures through an escalation model (default: self.model = Sonnet).
  Quality gate rejects: (a) summary/refusal responses, (b) suspected
  footnote-definition hallucinations (≤3 [^N]: lines on a short page).
  Typical cost: ~$0.40 for 418 pages vs $1.78 Sonnet-only.
"""

from __future__ import annotations

import base64
import io
import os
import re
import time
from pathlib import Path

from PIL import Image

from doc2md.extract.ocr_engines.base import OcrResult
from doc2md.models import Page

BATCH_THRESHOLD = 10
_BATCH_CHUNK = 50     # max images per Batch API submission (keeps POST body < ~100 MB)
_POLL_BASE = 60       # seconds — first poll delay
_POLL_MAX = 600       # seconds — cap on poll interval

# --- Quality gate patterns ---

_SUMMARY_RE = re.compile(
    r"^(Here is a (summary|brief summary)|Here's a (summary|brief summary)"
    r"|This appears to be|I can provide a summary"
    r"|rather than a verbatim|The passage describes|The author describes)",
    re.IGNORECASE | re.MULTILINE,
)
_FN_DEF_RE = re.compile(r"^\[\^\d+\]:", re.MULTILINE)

# Max footnote-def lines / max total lines to flag as hallucination
_FN_DEF_MAX = 3
_FN_DEF_LINE_THRESHOLD = 30


def quality_ok(result: OcrResult) -> bool:
    """Return False if result should be escalated to a stronger model.

    Rejects:
    - Summary or refusal responses (model paraphrased instead of transcribing)
    - Suspected footnote-definition hallucinations: ≤3 [^N]: lines on a page
      with fewer than 30 total lines (real Notes pages have many more lines)
    """
    text = (result.page.raw_text or "").strip()
    if not text:
        return True  # image-only page — nothing to escalate
    if _SUMMARY_RE.search(text):
        return False
    fn_defs = _FN_DEF_RE.findall(text)
    if fn_defs and len(fn_defs) <= _FN_DEF_MAX and result.line_count < _FN_DEF_LINE_THRESHOLD:
        return False
    return True

from doc2md.extract.ocr_engines.prompts import BASE_PROMPT


class ClaudeApiEngine:
    """Claude API vision engine (claude-sonnet-4-6).

    use_batch=None  → auto: real-time for ≤10 pages, Batch API for >10
    use_batch=True  → always use Batch API
    use_batch=False → always use real-time

    prompt defaults to BASE_PROMPT; pass build_prompt(book) for book-specific instructions.
    """

    name = "claude_api"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 2048,
        api_key: str | None = None,
        use_batch: bool | None = None,
        prompt: str | None = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self._api_key = api_key
        self.use_batch = use_batch
        self._prompt = prompt if prompt is not None else BASE_PROMPT
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def ocr_batch(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool = False,
    ) -> list[OcrResult]:
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        use_batch = self.use_batch
        if use_batch is None:
            use_batch = len(items) > BATCH_THRESHOLD

        if use_batch:
            return self._ocr_batch_api(items, auto_number=auto_number)
        return self._ocr_realtime(items, auto_number=auto_number)

    def ocr_batch_cascade(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        primary_model: str = "claude-haiku-4-5-20251001",
        primary_max_tokens: int = 2048,
        auto_number: bool = False,
    ) -> tuple[list[OcrResult], dict[str, int]]:
        """Two-stage cascade: primary_model first, self.model for quality failures.

        Returns (results, token_counts) where token_counts has keys:
        primary_input, primary_output, escalation_input, escalation_output.
        Results are in the same order as items.
        """
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # --- Stage 1: primary model (Haiku) ---
        primary_engine = ClaudeApiEngine(
            model=primary_model,
            max_tokens=primary_max_tokens,
            api_key=self._api_key,
            use_batch=self.use_batch,
            prompt=self._prompt,
        )
        print(f"  [cascade] stage 1: {primary_model} on {len(items)} pages", flush=True)
        primary_results = primary_engine.ocr_batch(items, auto_number=False)

        token_counts = {
            "primary_input": primary_engine.total_input_tokens,
            "primary_output": primary_engine.total_output_tokens,
            "escalation_input": 0,
            "escalation_output": 0,
        }

        # --- Identify failures ---
        fail_indices = [i for i, r in enumerate(primary_results) if not quality_ok(r)]
        print(
            f"  [cascade] {len(fail_indices)}/{len(items)} pages failed quality gate "
            f"→ escalating to {self.model}",
            flush=True,
        )

        # --- Stage 2: escalation model (Sonnet) on failures ---
        results = list(primary_results)
        if fail_indices:
            fail_items = [items[i] for i in fail_indices]
            escalation_engine = ClaudeApiEngine(
                model=self.model,
                max_tokens=self.max_tokens,
                api_key=self._api_key,
                use_batch=self.use_batch,
                prompt=self._prompt,
            )
            escalation_results = escalation_engine.ocr_batch(fail_items, auto_number=False)
            token_counts["escalation_input"] = escalation_engine.total_input_tokens
            token_counts["escalation_output"] = escalation_engine.total_output_tokens
            for idx, result in zip(fail_indices, escalation_results):
                results[idx] = result

        # Re-apply page numbers if requested
        if auto_number:
            for i, r in enumerate(results):
                r.page.page_number = i + 1

        self.total_input_tokens = token_counts["primary_input"] + token_counts["escalation_input"]
        self.total_output_tokens = token_counts["primary_output"] + token_counts["escalation_output"]
        return results, token_counts

    # ------------------------------------------------------------------
    # Real-time path
    # ------------------------------------------------------------------

    def _ocr_realtime(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool,
    ) -> list[OcrResult]:
        client = self._client()
        results: list[OcrResult] = []

        for idx, (image, source_path) in enumerate(items):
            t0 = time.monotonic()
            text, input_tokens, output_tokens = self._extract_one(client, image)
            elapsed = time.monotonic() - t0

            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            line_count = len([l for l in text.splitlines() if l.strip()])
            page = Page(
                source_path=source_path,
                raw_text=text,
                extraction_method=self.name,
                page_number=(idx + 1) if auto_number else None,
            )
            results.append(OcrResult(page=page, confidence=1.0, line_count=line_count))
            print(
                f"  [{self.name}] page {idx+1}/{len(items)}: "
                f"{input_tokens}in/{output_tokens}out tokens, "
                f"{line_count} lines, {elapsed:.1f}s"
            )

        return results

    def _extract_one(self, client, image: Image.Image) -> tuple[str, int, int]:
        """Send one image to the real-time API; return (text, input_tokens, output_tokens)."""
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": _image_message(image, self._prompt)}],
        )
        text = response.content[0].text
        return text, response.usage.input_tokens, response.usage.output_tokens

    # ------------------------------------------------------------------
    # Batch API path
    # ------------------------------------------------------------------

    def _ocr_batch_api(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool,
    ) -> list[OcrResult]:
        client = self._client()
        chunks = [items[i:i + _BATCH_CHUNK] for i in range(0, len(items), _BATCH_CHUNK)]
        print(
            f"  [{self.name}] {len(items)} images → "
            f"{len(chunks)} sub-batch(es) of ≤{_BATCH_CHUNK}"
        )

        # Submit all chunks, collecting (batch_id, global_offset) pairs
        submissions: list[tuple[str, int]] = []
        for chunk_idx, chunk in enumerate(chunks):
            global_offset = chunk_idx * _BATCH_CHUNK
            requests = [
                {
                    "custom_id": str(global_offset + i),
                    "params": {
                        "model": self.model,
                        "max_tokens": self.max_tokens,
                        "messages": [{"role": "user", "content": _image_message(img, self._prompt)}],
                    },
                }
                for i, (img, _) in enumerate(chunk)
            ]
            batch = client.messages.batches.create(requests=requests)
            submissions.append((batch.id, global_offset))
            print(
                f"  [{self.name}] sub-batch {chunk_idx+1}/{len(chunks)} submitted: "
                f"{batch.id} ({len(chunk)} requests, offset {global_offset})",
                flush=True,
            )

        # Poll all batches until every one has ended
        texts: dict[int, tuple[str, int, int]] = {}
        pending = list(submissions)
        while pending:
            time.sleep(_POLL_BASE)
            still_pending = []
            for batch_id, offset in pending:
                batch = client.messages.batches.retrieve(batch_id)
                c = batch.request_counts
                print(
                    f"  [{self.name}] {batch_id}: "
                    f"{c.processing} processing, {c.succeeded} succeeded, {c.errored} errored",
                    flush=True,
                )
                if batch.processing_status == "ended":
                    for result in client.messages.batches.results(batch_id):
                        idx = int(result.custom_id)
                        if result.result.type == "succeeded":
                            msg = result.result.message
                            texts[idx] = (
                                msg.content[0].text,
                                msg.usage.input_tokens,
                                msg.usage.output_tokens,
                            )
                        else:
                            print(f"  [{self.name}] warning: page {idx} type={result.result.type}")
                            texts[idx] = ("", 0, 0)
                else:
                    still_pending.append((batch_id, offset))
            pending = still_pending

        results: list[OcrResult] = []
        for idx, (image, source_path) in enumerate(items):
            text, input_tokens, output_tokens = texts.get(idx, ("", 0, 0))
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            line_count = len([l for l in text.splitlines() if l.strip()])
            page = Page(
                source_path=source_path,
                raw_text=text,
                extraction_method=self.name,
                page_number=(idx + 1) if auto_number else None,
            )
            results.append(OcrResult(page=page, confidence=1.0, line_count=line_count))

        print(
            f"  [{self.name}] all batches done: "
            f"{self.total_input_tokens}in/{self.total_output_tokens}out tokens total",
            flush=True,
        )
        return results

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _client(self):
        import anthropic
        import httpx
        # ALL_PROXY may point to a SOCKS5 address requiring socksio.
        # Use the HTTP proxy explicitly to avoid that dependency.
        http_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        transport = httpx.HTTPTransport(proxy=http_proxy) if http_proxy else None
        http_client = httpx.Client(transport=transport) if transport else None
        return anthropic.Anthropic(api_key=self._api_key, http_client=http_client)


def _image_message(image: Image.Image, prompt: str) -> list[dict]:
    """Build the content list for a single-image user message."""
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": _encode_image(image),
            },
        },
        {"type": "text", "text": prompt},
    ]


def _encode_image(image: Image.Image) -> str:
    """PNG-encode image and return base64 string."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode()
