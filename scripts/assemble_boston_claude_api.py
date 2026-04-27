"""Assemble per-page .txt files from the Claude API run into a single Markdown file.

Blank/image-only pages are skipped silently.
Summary/refusal pages are included but wrapped in an HTML comment so they're
visible when reviewing but don't pollute the reading experience.
"""

import re
import sys
from pathlib import Path

_repo = Path(__file__).parent.parent
IN_DIR  = _repo / "results" / "boston_claude_api"
OUT_MD  = IN_DIR / "chapter_01_untitled.md"

_BLANK_RE = re.compile(
    r"^(The image appears to be|This image (appears|is) (entirely|completely) blank"
    r"|entirely blank|completely blank"
    r"|solid\s+\S+\s+colored rectangle"
    r"|no visible text content)",
    re.IGNORECASE,
)
_SUMMARY_RE = re.compile(
    r"^(Here is a (summary|brief summary)|Here's a (summary|brief summary)"
    r"|This appears to be|I can provide a summary"
    r"|rather than a verbatim|The passage describes|The author describes)",
    re.IGNORECASE | re.MULTILINE,
)


def classify(text: str) -> str:
    """Return 'blank', 'summary', or 'ok'."""
    stripped = text.strip()
    if not stripped:
        return "blank"
    if _BLANK_RE.match(stripped):
        return "blank"
    if _SUMMARY_RE.search(stripped):
        return "summary"
    return "ok"


def main():
    txt_files = sorted(IN_DIR.glob("*.txt"))
    if not txt_files:
        sys.exit(f"No .txt files in {IN_DIR}")

    blanks = summaries = ok = 0
    parts: list[str] = []

    for path in txt_files:
        text = path.read_text().strip()
        kind = classify(text)
        if kind == "blank":
            blanks += 1
        elif kind == "summary":
            summaries += 1
            parts.append(f"<!-- SUMMARY (page {path.stem}) -->\n{text}\n<!-- /SUMMARY -->")
        else:
            ok += 1
            parts.append(text)

    output = "\n\n".join(parts)
    OUT_MD.write_text(output + "\n")

    total = len(txt_files)
    print(f"Pages: {total} total — {ok} transcribed, {summaries} summaries, {blanks} blank")
    print(f"Output: {OUT_MD}  ({OUT_MD.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
