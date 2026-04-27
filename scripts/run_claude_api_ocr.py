"""Claude API vision OCR for any screenshot folder.

Auto-detects folder type:
  - Libby spreads  (landscape, uniform dims) → midpoint split, no chrome crop
  - Browser screenshots (chrome detected)    → chrome crop, no split
  - Plain screenshots                        → no crop, no split

Runs Sonnet Batch API by default. Use --cascade for Haiku-first escalation.

Output: results/<folder_name>/<NNN>.txt + summary.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_repo = Path(__file__).parent.parent
_env_file = _repo / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

sys.path.insert(0, str(_repo / "src"))

from PIL import Image
from doc2md.extract.chrome_cropper import detect_content_bounds, crop_image
from doc2md.extract.ocr_extract import _get_image_files
from doc2md.extract.screenshot_extract import is_libby_spread
from doc2md.extract.ocr_engines.claude_api import ClaudeApiEngine
from doc2md.extract.ocr_engines.prompts import build_prompt, KNOWN_BOOKS

# Batch API pricing (50% off real-time)
_PRICING = {
    "claude-sonnet-4-6":         (1.50, 7.50),
    "claude-haiku-4-5-20251001": (0.40, 2.00),
}
_DEFAULT_PRICING = (1.50, 7.50)


def _cost(input_tokens: int, output_tokens: int, model: str) -> float:
    in_m, out_m = _PRICING.get(model, _DEFAULT_PRICING)
    return (input_tokens / 1_000_000) * in_m + (output_tokens / 1_000_000) * out_m


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def build_items(
    folder: Path,
) -> tuple[list[tuple[Image.Image, Path]], str]:
    """Load images from folder, applying split/crop as needed.

    Returns (items, mode_description).
    """
    image_files = _get_image_files(folder)
    if not image_files:
        raise SystemExit(f"No images found in {folder}")

    bounds = detect_content_bounds(image_files)

    if is_libby_spread(folder):
        # Landscape two-page spreads: split at midpoint, no chrome crop
        items = []
        for path in image_files:
            img = Image.open(path)
            mid = img.width // 2
            items.append((img.crop((0, 0, mid, img.height)), path))
            items.append((img.crop((mid, 0, img.width, img.height)), path))
        mode = f"libby-spread ({len(image_files)} spreads → {len(items)} half-pages)"
    else:
        items = []
        for path in image_files:
            img = Image.open(path)
            if bounds:
                img = crop_image(img, bounds)
            items.append((img, path))
        if bounds:
            l, t, r, b = bounds
            mode = f"browser-screenshot ({len(items)} pages, cropped to {r-l}×{b-t} px)"
        else:
            mode = f"plain-screenshot ({len(items)} pages, no crop)"

    return items, mode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Screenshot folder to process")
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Output directory (default: results/<folder_name>)",
    )
    parser.add_argument(
        "--cascade", action="store_true",
        help="Haiku first, Sonnet only for quality failures (cheaper)",
    )
    parser.add_argument(
        "--book", default=None, metavar="KEY",
        help=f"Book-specific prompt additions. Known keys: {', '.join(KNOWN_BOOKS)}",
    )
    args = parser.parse_args()

    folder = args.folder.expanduser().resolve()
    if not folder.is_dir():
        raise SystemExit(f"Not a directory: {folder}")

    out_dir = args.output_dir or (_repo / "results" / folder.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{_ts()}] Input:  {folder}", flush=True)
    print(f"[{_ts()}] Output: {out_dir}", flush=True)

    items, mode = build_items(folder)
    sample_w, sample_h = items[0][0].size
    print(
        f"[{_ts()}] Mode: {mode}  ({sample_w}×{sample_h} px per item)",
        flush=True,
    )

    prompt = build_prompt(args.book)
    if args.book:
        print(f"[{_ts()}] Prompt: {args.book} (tailored)", flush=True)
    else:
        print(f"[{_ts()}] Prompt: base", flush=True)

    engine = ClaudeApiEngine(use_batch=True, prompt=prompt)  # Sonnet, Batch API
    t0 = time.monotonic()

    if args.cascade:
        print(f"[{_ts()}] OCR: cascade (Haiku → Sonnet for failures)", flush=True)
        results, token_counts = engine.ocr_batch_cascade(items, auto_number=True)
        elapsed = time.monotonic() - t0

        haiku_model = "claude-haiku-4-5-20251001"
        sonnet_model = "claude-sonnet-4-6"
        haiku_cost = _cost(token_counts["primary_input"], token_counts["primary_output"], haiku_model)
        sonnet_cost = _cost(token_counts["escalation_input"], token_counts["escalation_output"], sonnet_model)
        total_cost = haiku_cost + sonnet_cost
        cost_detail = {
            "haiku_input_tokens":  token_counts["primary_input"],
            "haiku_output_tokens": token_counts["primary_output"],
            "haiku_cost_usd":      round(haiku_cost, 4),
            "sonnet_input_tokens": token_counts["escalation_input"],
            "sonnet_output_tokens":token_counts["escalation_output"],
            "sonnet_cost_usd":     round(sonnet_cost, 4),
        }
        print(
            f"[{_ts()}] Haiku:  {token_counts['primary_input']}in/"
            f"{token_counts['primary_output']}out  ${haiku_cost:.4f}  |  "
            f"Sonnet: {token_counts['escalation_input']}in/"
            f"{token_counts['escalation_output']}out  ${sonnet_cost:.4f}",
            flush=True,
        )
    else:
        print(f"[{_ts()}] OCR: Sonnet Batch API", flush=True)
        results = engine.ocr_batch(items, auto_number=True)
        elapsed = time.monotonic() - t0
        total_cost = _cost(engine.total_input_tokens, engine.total_output_tokens, "claude-sonnet-4-6")
        cost_detail = {
            "sonnet_input_tokens":  engine.total_input_tokens,
            "sonnet_output_tokens": engine.total_output_tokens,
            "sonnet_cost_usd":      round(total_cost, 4),
        }

    print(f"[{_ts()}] Saving {len(results)} pages …", flush=True)
    manifest = []
    for result in results:
        page = result.page
        out_path = out_dir / f"{page.page_number:04d}.txt"
        out_path.write_text(page.raw_text or "")
        manifest.append({
            "page_number":  page.page_number,
            "source":       page.source_path.name,
            "line_count":   result.line_count,
            "out_path":     str(out_path.relative_to(_repo)),
        })

    summary = {
        "folder":    str(folder),
        "mode":      mode,
        "book":      args.book,
        "ocr_mode":  "cascade" if args.cascade else "sonnet-only",
        "pages":     len(results),
        "cost_usd":  round(total_cost, 4),
        "elapsed_s": round(elapsed, 1),
        **cost_detail,
        "manifest":  manifest,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(
        f"[{_ts()}] Done.  {len(results)} pages  ${total_cost:.4f}  {elapsed/60:.1f} min",
        flush=True,
    )
    print(f"[{_ts()}] Summary → {summary_path}", flush=True)


if __name__ == "__main__":
    main()
