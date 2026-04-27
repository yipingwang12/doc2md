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
"""

from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path

from PIL import Image

from doc2md.extract.ocr_engines.base import OcrResult
from doc2md.models import Page

BATCH_THRESHOLD = 10
_BATCH_CHUNK = 50     # max images per Batch API submission (keeps POST body < ~100 MB)
_POLL_BASE = 60       # seconds — first poll delay
_POLL_MAX = 600       # seconds — cap on poll interval

_PROMPT = """\
Transcribe every word on this book page verbatim into Markdown. Do NOT summarize or paraphrase.
- Headings: use # / ## / ### based on apparent visual hierarchy
- Body text: reproduce word-for-word, joining hyphenated line-breaks
- Footnote markers in body text: keep inline as `[^N]`
- Footnote definitions: emit as `[^N]: text` ONLY if the full footnote text is visible on this page; never invent placeholder definitions
- Figure captions: emit as `> caption text`
- Page numbers, running headers/footers: omit
- Purely decorative images with no text: output nothing
Output only the Markdown, no preamble or explanation."""


class ClaudeApiEngine:
    """Claude API vision engine (claude-sonnet-4-6).

    use_batch=None  → auto: real-time for ≤10 pages, Batch API for >10
    use_batch=True  → always use Batch API
    use_batch=False → always use real-time
    """

    name = "claude_api"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 2048,
        api_key: str | None = None,
        use_batch: bool | None = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self._api_key = api_key
        self.use_batch = use_batch
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
            messages=[{"role": "user", "content": _image_message(image)}],
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
                        "messages": [{"role": "user", "content": _image_message(img)}],
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


def _image_message(image: Image.Image) -> list[dict]:
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
        {"type": "text", "text": _PROMPT},
    ]


def _encode_image(image: Image.Image) -> str:
    """PNG-encode image and return base64 string."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode()
