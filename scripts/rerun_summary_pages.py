"""Re-run summary/refusal pages through Haiku real-time API.

Reads results/boston_claude_api/*.txt, identifies pages that contain a
summary/refusal rather than a verbatim transcription, reconstructs the
original half-page images, and re-runs them through claude-haiku-4-5-20251001.
Overwrites the .txt files on success.
"""

import os
import re
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
INPUT_COST_PER_M  = 0.80
OUTPUT_COST_PER_M = 4.00

_SUMMARY_RE = re.compile(
    r"^(Here is a (summary|brief summary)|Here's a (summary|brief summary)"
    r"|This appears to be|I can provide a summary"
    r"|rather than a verbatim|The passage describes|The author describes)",
    re.IGNORECASE | re.MULTILINE,
)


def is_summary(text: str) -> bool:
    return bool(_SUMMARY_RE.search(text.strip()))


def page_to_half_image(page_number: int, image_files: list[Path]) -> tuple[Image.Image, Path]:
    """Convert 1-based page number to (half_image, source_path)."""
    idx = page_number - 1
    spread_idx = idx // 2
    side = idx % 2          # 0 = left, 1 = right
    spread_path = image_files[spread_idx]
    img = Image.open(spread_path)
    midx = img.width // 2
    if side == 0:
        return img.crop((0, 0, midx, img.height)), spread_path
    else:
        return img.crop((midx, 0, img.width, img.height)), spread_path


def main():
    image_files = sorted(BOSTON_DIR.glob("*.png")) + sorted(BOSTON_DIR.glob("*.jpg"))

    # Find all summary pages
    summary_pages: list[int] = []
    for txt_path in sorted(OUT_DIR.glob("*.txt")):
        text = txt_path.read_text()
        if is_summary(text):
            page_num = int(txt_path.stem)
            summary_pages.append(page_num)

    print(f"Found {len(summary_pages)} summary pages: {summary_pages}")

    # Build (image, source_path) items in page-number order
    items = [page_to_half_image(p, image_files) for p in summary_pages]

    engine = ClaudeApiEngine(model="claude-haiku-4-5-20251001", use_batch=False)
    t0 = time.monotonic()
    results = engine.ocr_batch(items, auto_number=False)
    elapsed = time.monotonic() - t0

    # Overwrite .txt files with new results
    fixed = skipped = 0
    for page_num, result in zip(summary_pages, results):
        new_text = result.page.raw_text or ""
        if is_summary(new_text):
            print(f"  page {page_num:04d}: still a summary after Haiku — keeping original")
            skipped += 1
        else:
            out_path = OUT_DIR / f"{page_num:04d}.txt"
            out_path.write_text(new_text)
            fixed += 1

    total_in  = engine.total_input_tokens
    total_out = engine.total_output_tokens
    cost = (total_in / 1_000_000) * INPUT_COST_PER_M + (total_out / 1_000_000) * OUTPUT_COST_PER_M
    print(f"\nFixed {fixed}/{len(summary_pages)} pages, {skipped} still summaries")
    print(f"Tokens: {total_in}in / {total_out}out  Cost: ${cost:.4f}  Time: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
