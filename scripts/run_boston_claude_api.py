"""Production run: Claude API on the full Boston Artifacts book.

Default: all pages via Sonnet + Batch API.
--cascade: Haiku first (Batch API), Sonnet only for quality failures.

Quality failures = summary/refusal responses + suspected footnote-definition
hallucinations (≤3 [^N]: lines on a short page).

Saves per-page text to results/boston_claude_api/<NNN>.txt and summary JSON.
"""

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
from doc2md.extract.ocr_engines.claude_api import ClaudeApiEngine

BOSTON_DIR = _repo / "synced" / "a_history_of_boston_in_50_artifacts"
OUT_DIR    = _repo / "results" / "boston_claude_api"

# Batch API pricing (50% off real-time)
_PRICING = {
    "claude-sonnet-4-6":          (1.50, 7.50),
    "claude-haiku-4-5-20251001":  (0.40, 2.00),
}
_DEFAULT_PRICING = (1.50, 7.50)


def _cost(input_tokens: int, output_tokens: int, model: str) -> float:
    in_m, out_m = _PRICING.get(model, _DEFAULT_PRICING)
    return (input_tokens / 1_000_000) * in_m + (output_tokens / 1_000_000) * out_m


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cascade", action="store_true",
        help="Haiku first, Sonnet only for quality failures (cheaper)",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    image_files = sorted(BOSTON_DIR.glob("*.png")) + sorted(BOSTON_DIR.glob("*.jpg"))
    print(f"[{_ts()}] Found {len(image_files)} spreads", flush=True)

    halves = []
    for spread_path in image_files:
        img = Image.open(spread_path)
        midx = img.width // 2
        halves.append((img.crop((0, 0, midx, img.height)), spread_path))
        halves.append((img.crop((midx, 0, img.width, img.height)), spread_path))
    print(
        f"[{_ts()}] Split into {len(halves)} half-pages "
        f"({halves[0][0].size[0]}×{halves[0][0].size[1]} px)",
        flush=True,
    )

    engine = ClaudeApiEngine(use_batch=True)  # Sonnet, Batch API
    t0 = time.monotonic()

    if args.cascade:
        print(f"[{_ts()}] Mode: cascade (Haiku → Sonnet for failures)", flush=True)
        results, token_counts = engine.ocr_batch_cascade(halves, auto_number=True)
        elapsed = time.monotonic() - t0

        haiku_model = "claude-haiku-4-5-20251001"
        sonnet_model = "claude-sonnet-4-6"
        haiku_cost = _cost(token_counts["primary_input"], token_counts["primary_output"], haiku_model)
        sonnet_cost = _cost(token_counts["escalation_input"], token_counts["escalation_output"], sonnet_model)
        total_cost = haiku_cost + sonnet_cost

        cost_detail = {
            "haiku_input_tokens": token_counts["primary_input"],
            "haiku_output_tokens": token_counts["primary_output"],
            "haiku_cost_usd": round(haiku_cost, 4),
            "sonnet_input_tokens": token_counts["escalation_input"],
            "sonnet_output_tokens": token_counts["escalation_output"],
            "sonnet_cost_usd": round(sonnet_cost, 4),
        }
        print(
            f"[{_ts()}] Haiku: {token_counts['primary_input']}in/"
            f"{token_counts['primary_output']}out ${haiku_cost:.4f}  "
            f"Sonnet: {token_counts['escalation_input']}in/"
            f"{token_counts['escalation_output']}out ${sonnet_cost:.4f}",
            flush=True,
        )
    else:
        print(f"[{_ts()}] Mode: Sonnet-only (Batch API)", flush=True)
        results = engine.ocr_batch(halves, auto_number=True)
        elapsed = time.monotonic() - t0
        total_cost = _cost(engine.total_input_tokens, engine.total_output_tokens, "claude-sonnet-4-6")
        cost_detail = {
            "sonnet_input_tokens": engine.total_input_tokens,
            "sonnet_output_tokens": engine.total_output_tokens,
            "sonnet_cost_usd": round(total_cost, 4),
        }

    print(f"[{_ts()}] Saving {len(results)} pages to {OUT_DIR} …", flush=True)
    manifest = []
    for result in results:
        page = result.page
        out_path = OUT_DIR / f"{page.page_number:04d}.txt"
        out_path.write_text(page.raw_text or "")
        manifest.append({
            "page_number": page.page_number,
            "source": page.source_path.name,
            "line_count": result.line_count,
            "model": page.extraction_method,
            "out_path": str(out_path.relative_to(_repo)),
        })

    summary = {
        "mode": "cascade" if args.cascade else "sonnet-only",
        "pages": len(results),
        "cost_usd": round(total_cost, 4),
        "elapsed_s": round(elapsed, 1),
        **cost_detail,
        "manifest": manifest,
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(
        f"[{_ts()}] Done. {len(results)} pages, ${total_cost:.4f}, {elapsed/60:.1f} min",
        flush=True,
    )
    print(f"[{_ts()}] Summary → {summary_path}", flush=True)


def _ts():
    return time.strftime("%H:%M:%S")


if __name__ == "__main__":
    main()
