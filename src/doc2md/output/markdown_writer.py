"""Render Chapter objects to Markdown files."""

from __future__ import annotations

import re
from pathlib import Path

from doc2md.models import Chapter


def render_chapter(chapter: Chapter) -> str:
    """Render a chapter to a Markdown string."""
    parts: list[str] = []

    # Title
    prefix = "#" * chapter.heading_level
    parts.append(f"{prefix} {chapter.title}")
    parts.append("")

    for block in chapter.blocks:
        if block.block_type == "heading":
            level = block.heading_level or 2
            h_prefix = "#" * (level + 1) if level <= 2 else "####"
            parts.append(f"{h_prefix} {block.text}")
            parts.append("")
        elif block.block_type == "body":
            parts.append(block.text)
            parts.append("")
        elif block.block_type == "caption":
            parts.append(f"> {block.text}")
            parts.append("")
        elif block.block_type == "index":
            parts.append(f"- {block.text}")

    # Footnotes section
    if chapter.footnotes:
        parts.append("")
        for fid in sorted(chapter.footnotes, key=_footnote_sort_key):
            parts.append(f"[^{fid}]: {chapter.footnotes[fid]}")
        parts.append("")

    # Bibliography section
    if chapter.bibliography:
        parts.append("")
        parts.append("## References")
        parts.append("")
        for i, ref in enumerate(chapter.bibliography, 1):
            parts.append(f"{i}. {ref}")
        parts.append("")

    return "\n".join(parts)


def _footnote_sort_key(fid: str) -> tuple[int, str]:
    """Sort footnote IDs numerically if possible."""
    try:
        return (0, str(int(fid)).zfill(10))
    except ValueError:
        return (1, fid)


def slugify(text: str) -> str:
    """Convert a title to a filename-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "_", slug)
    slug = slug.strip("_")
    return slug[:60]


def write_chapters(chapters: list[Chapter], output_dir: Path, doc_name: str) -> list[Path]:
    """Write each chapter to a separate .md file."""
    doc_dir = output_dir / slugify(doc_name)
    doc_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for i, chapter in enumerate(chapters, 1):
        slug = slugify(chapter.title)
        filename = f"chapter_{i:02d}_{slug}.md"
        path = doc_dir / filename
        path.write_text(render_chapter(chapter))
        paths.append(path)

    return paths
