"""Demo: Claude API OCR on 4 half-pages from the middle of Boston Artifacts.

Picks 2 consecutive spreads from the middle of the book, splits each at the
midpoint (→ 4 half-pages), sends them to the specified model, and prints the
resulting Markdown with timing and cost summary.

Usage:
  python scripts/demo_claude_api.py [--model MODEL]

  --model  Claude model ID (default: claude-sonnet-4-6)
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Load .env before importing doc2md so ANTHROPIC_API_KEY is in the environment.
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

# Per-million-token pricing as of 2025
_PRICING = {
    "claude-sonnet-4-6":        (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80,  4.00),
    "claude-haiku-4-5":          (0.80,  4.00),
    "claude-opus-4-7":          (15.00, 75.00),
}
_DEFAULT_PRICING = (3.00, 15.00)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Claude model ID")
    parser.add_argument("--scale", type=float, default=1.0, help="Resize factor before sending (e.g. 0.5)")
    args = parser.parse_args()

    image_files = sorted(BOSTON_DIR.glob("*.png")) + sorted(BOSTON_DIR.glob("*.jpg"))
    if not image_files:
        sys.exit(f"No images found in {BOSTON_DIR}")

    total = len(image_files)
    mid = total // 2
    chosen_spreads = image_files[mid : mid + 2]
    print(f"Model: {args.model}")
    print(f"Boston: {total} spreads total. Using spreads {mid} and {mid+1}:")
    for f in chosen_spreads:
        print(f"  {f.name}")

    halves: list[tuple[Image.Image, Path]] = []
    for spread_path in chosen_spreads:
        img = Image.open(spread_path)
        midx = img.width // 2
        halves.append((img.crop((0, 0, midx, img.height)), spread_path))
        halves.append((img.crop((midx, 0, img.width, img.height)), spread_path))

    if args.scale != 1.0:
        new_w = int(halves[0][0].width * args.scale)
        new_h = int(halves[0][0].height * args.scale)
        halves = [(img.resize((new_w, new_h), Image.LANCZOS), path) for img, path in halves]

    w, h = halves[0][0].size
    print(f"\nSplit into {len(halves)} half-pages ({w}×{h} px each, scale={args.scale})\n")

    engine = ClaudeApiEngine(model=args.model)
    t0 = time.monotonic()
    results = engine.ocr_batch(halves, auto_number=True)
    total_elapsed = time.monotonic() - t0

    for i, result in enumerate(results):
        spread_name = result.page.source_path.stem
        side = "left" if i % 2 == 0 else "right"
        print(f"\n{'='*70}")
        print(f"Page {result.page.page_number} — {spread_name} ({side})")
        print("=" * 70)
        print(result.page.raw_text or "(empty)")

    total_in = engine.total_input_tokens
    total_out = engine.total_output_tokens
    in_cost, out_cost = _PRICING.get(args.model, _DEFAULT_PRICING)
    cost = (total_in / 1_000_000) * in_cost + (total_out / 1_000_000) * out_cost

    print(f"\n{'='*70}")
    print(f"Model: {args.model}")
    print(f"Total wall-clock: {total_elapsed:.1f}s for {len(halves)} pages")
    print(f"Total tokens: {total_in} input + {total_out} output")
    print(f"Estimated cost: ${cost:.4f}")


if __name__ == "__main__":
    main()
