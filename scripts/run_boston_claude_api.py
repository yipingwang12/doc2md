"""Production run: Claude API (Sonnet + Batch API) on full Boston Artifacts book.

Splits all 209 spreads at midpoint → 418 half-pages, submits as a single
Batch API job, polls until complete, then saves per-page text to
results/boston_claude_api/<NNN>.txt and a summary JSON.
"""

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
OUT_DIR = _repo / "results" / "boston_claude_api"
INPUT_COST_PER_M  = 1.50   # Sonnet + 50% batch discount
OUTPUT_COST_PER_M = 7.50


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    image_files = sorted(BOSTON_DIR.glob("*.png")) + sorted(BOSTON_DIR.glob("*.jpg"))
    print(f"[{_ts()}] Found {len(image_files)} spreads", flush=True)

    halves = []
    for spread_path in image_files:
        img = Image.open(spread_path)
        midx = img.width // 2
        halves.append((img.crop((0, 0, midx, img.height)), spread_path))
        halves.append((img.crop((midx, 0, img.width, img.height)), spread_path))
    print(f"[{_ts()}] Split into {len(halves)} half-pages ({halves[0][0].size[0]}×{halves[0][0].size[1]} px)", flush=True)

    engine = ClaudeApiEngine(use_batch=True)
    t0 = time.monotonic()
    results = engine.ocr_batch(halves, auto_number=True)
    elapsed = time.monotonic() - t0

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
            "out_path": str(out_path.relative_to(_repo)),
        })

    total_in  = engine.total_input_tokens
    total_out = engine.total_output_tokens
    cost = (total_in / 1_000_000) * INPUT_COST_PER_M + (total_out / 1_000_000) * OUTPUT_COST_PER_M

    summary = {
        "pages": len(results),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "cost_usd": round(cost, 4),
        "elapsed_s": round(elapsed, 1),
        "manifest": manifest,
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(f"[{_ts()}] Done. {len(results)} pages, {total_in}in/{total_out}out tokens, ${cost:.4f}, {elapsed/60:.1f} min", flush=True)
    print(f"[{_ts()}] Summary → {summary_path}", flush=True)


def _ts():
    return time.strftime("%H:%M:%S")


if __name__ == "__main__":
    main()
