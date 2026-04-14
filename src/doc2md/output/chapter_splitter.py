"""Split a single-file markdown book into per-chapter directories.

Detects chapter boundaries (PART headers, named sections like Preface,
Introduction, Conclusion, Appendix, Notes, Bibliography, Index) and
writes each chapter to its own numbered directory.

Supports artifact-level splitting: within PART sections, detects
individual numbered items via headings (``N. Title``) or figure
references (``FIGURE N.1``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from doc2md.output.markdown_writer import slugify


@dataclass
class ChapterDef:
    """A detected chapter boundary."""

    title: str
    start_line: int  # 0-based inclusive
    end_line: int | None = None  # exclusive; None = EOF
    page_start: int | None = None
    page_end: int | None = None


# --- Patterns for chapter boundary detection ---

# PART N Title (may wrap to next line)
_PART_RE = re.compile(r"^PART\s+(\d+)\s+(.+)$", re.IGNORECASE)
# Named front/back matter sections (bold or plain)
_NAMED_SECTION_RE = re.compile(
    r"^(?:<b>)?(Preface|Acknowledgments|Introduction|Notes|Bibliography|Index)(?:</b>)?$",
)
# CONCLUSION. Title or APPENDIX. Title (may wrap)
_TITLED_SECTION_RE = re.compile(
    r"^(CONCLUSION|APPENDIX|AFTERWORD|FOREWORD|EPILOGUE|PROLOGUE)[.\s:]+(.+)$",
    re.IGNORECASE,
)
# TOC region markers
_CONTENTS_RE = re.compile(r"^(?:<b>)?Contents(?:</b>)?$", re.IGNORECASE)

_TAG_RE = re.compile(r"</?(?:b|i|math|sup)>")

# Artifact patterns (body region only)
_ARTIFACT_HEADING_RE = re.compile(r"^(\d+)\.\s+([A-Z][A-Za-z].*)$")
_FIGURE_RE = re.compile(r"FIGURE\s+(\d+)\.(\d+)")


def _strip_tags(text: str) -> str:
    """Remove HTML-like markup tags from text."""
    return _TAG_RE.sub("", text).strip()


def _is_toc_line(line: str) -> bool:
    """Check if a line looks like a TOC entry (numbered artifact listing)."""
    stripped = line.strip()
    return bool(re.match(r"^\d+\.\s+[A-Z]", stripped)) or bool(
        re.match(r"^PART\s+\d+\s+", stripped, re.IGNORECASE)
    )


def _find_toc_end(lines: list[str]) -> int:
    """Find the line index where the TOC region ends.

    The TOC starts at a "Contents" line. We find section names that
    appear in both the TOC and body — the body occurrence (the later
    one) marks where real content begins. Returns 0 if no TOC found.
    """
    contents_line = None
    for i, line in enumerate(lines):
        if _CONTENTS_RE.match(line.strip()):
            contents_line = i
            break

    if contents_line is None:
        return 0

    # Collect all positions of structural markers (named sections, PARTs)
    # and find duplicates: the first is in the TOC, the second is body.
    marker_positions: dict[str, list[int]] = {}
    for i in range(contents_line + 1, len(lines)):
        stripped = lines[i].strip()
        m = _NAMED_SECTION_RE.match(stripped)
        if m:
            key = m.group(1).lower()
            marker_positions.setdefault(key, []).append(i)
            continue
        m = _PART_RE.match(stripped)
        if m:
            key = f"part_{m.group(1)}"
            marker_positions.setdefault(key, []).append(i)

    # The TOC end is the earliest "second occurrence" of any marker
    body_starts: list[int] = []
    for positions in marker_positions.values():
        if len(positions) >= 2:
            body_starts.append(positions[1])

    if body_starts:
        return min(body_starts)

    # No duplicates found — no TOC to skip
    return 0


def _parse_toc_artifacts(lines: list[str], toc_end: int) -> dict[int, str]:
    """Extract artifact number→title mapping from the TOC region.

    Also checks the Appendix section (artifact provenances) for any
    items missing from the TOC (e.g. OCR split ``1.`` from its title).
    """
    titles: dict[int, str] = {}
    toc_artifact_re = re.compile(r"^(\d+)\.\s+(.+)$")
    # Bare number on its own line (e.g. "1.") — grab title from next line
    bare_num_re = re.compile(r"^(\d+)\.\s*$")

    for i in range(0, toc_end):
        stripped = lines[i].strip()
        m = toc_artifact_re.match(stripped)
        if m:
            num = int(m.group(1))
            title = m.group(2).strip()
            # Skip if title looks like dimensions (Appendix provenance)
            if 1 <= num <= 999 and not re.search(r"<math>|×|\bcm\b", title):
                titles[num] = title
            continue
        m = bare_num_re.match(stripped)
        if m and i > 0:
            num = int(m.group(1))
            # Previous line might be the title (OCR split)
            prev = lines[i - 1].strip()
            if prev and not prev.startswith("PART") and 1 <= num <= 999:
                titles[num] = prev

    # Fill gaps from Appendix (lines after toc_end with "N. Title, dimensions")
    appendix_re = re.compile(r"^(\d+)\.\s+(.+?),\s+(?:<math>|\d)")
    for i in range(toc_end, len(lines)):
        stripped = lines[i].strip()
        m = appendix_re.match(stripped)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 999 and num not in titles:
                titles[num] = m.group(2).strip()

    return titles


def _find_artifact_boundaries(
    lines: list[str], body_start: int, body_end: int, max_artifact: int,
) -> dict[int, int]:
    """Find the start line for each numbered artifact in the body region.

    Uses two markers (in priority order):
    1. Explicit heading: ``N. Title`` on its own line
    2. First figure reference: ``FIGURE N.1`` — backs up to preceding blank line

    Returns {artifact_number: start_line}.
    """
    headings: dict[int, int] = {}
    figures: dict[int, int] = {}

    for i in range(body_start, body_end):
        stripped = lines[i].strip()

        # Check for numbered heading (e.g. "3. Fishweir Stakes")
        m = _ARTIFACT_HEADING_RE.match(stripped)
        if m:
            num = int(m.group(1))
            if 1 <= num <= max_artifact and num not in headings:
                headings[num] = i

        # Check for FIGURE N.1 (any format: plain, >, <b>)
        clean = _strip_tags(stripped).lstrip("> ")
        m = _FIGURE_RE.match(clean)
        if m:
            num = int(m.group(1))
            fig_sub = int(m.group(2))
            if fig_sub == 1 and 1 <= num <= max_artifact and num not in figures:
                # Back up to preceding blank line (natural section break)
                start = i
                for j in range(i - 1, max(body_start - 1, i - 10), -1):
                    if not lines[j].strip():
                        start = j + 1
                        break
                figures[num] = start

    # Merge: prefer heading over figure
    result: dict[int, int] = {}
    for num in range(1, max_artifact + 1):
        if num in headings:
            result[num] = headings[num]
        elif num in figures:
            result[num] = figures[num]

    return result


def detect_chapters(
    lines: list[str], *, artifact_level: bool = False,
) -> list[ChapterDef]:
    """Detect chapter boundaries from markdown lines.

    Finds PART headers, named sections (Preface, Introduction, etc.),
    and titled sections (CONCLUSION, APPENDIX). Skips the TOC region
    to avoid false matches.

    When *artifact_level* is True, also splits within PART sections at
    individual numbered items (detected via headings or figure refs).
    """
    chapters: list[ChapterDef] = []
    toc_end = _find_toc_end(lines)
    # Track sections already emitted so running headers (same section
    # title repeating at every page top) don't create duplicate chapters.
    seen_named: set[str] = set()

    i = toc_end
    while i < len(lines):
        stripped = lines[i].strip()

        # Named section: Preface, Acknowledgments, Introduction, etc.
        m = _NAMED_SECTION_RE.match(stripped)
        if m:
            key = m.group(1).lower()
            if key in seen_named:
                i += 1
                continue
            seen_named.add(key)
            chapters.append(ChapterDef(title=m.group(1), start_line=i))
            i += 1
            continue

        # PART N Title (possibly wrapping to next line)
        m = _PART_RE.match(stripped)
        if m:
            part_num = m.group(1)
            title_text = _strip_tags(m.group(2).strip())
            # Check for wrapped continuation on next line
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not _PART_RE.match(next_line) and not _NAMED_SECTION_RE.match(next_line):
                    if not re.match(r"^\d+\.\s+[A-Z]", next_line):
                        title_text += " " + _strip_tags(next_line)
            chapters.append(
                ChapterDef(title=f"Part {part_num}: {title_text}", start_line=i)
            )
            i += 1
            continue

        # CONCLUSION. Title or APPENDIX. Title
        m = _TITLED_SECTION_RE.match(stripped)
        if m:
            # Reject mid-paragraph matches: real headers are short. OCR
            # can merge parallel columns into long lines that start with
            # a section word by coincidence.
            if len(_strip_tags(stripped)) > 80:
                i += 1
                continue
            key = m.group(1).lower()
            if key in seen_named:
                i += 1
                continue
            seen_named.add(key)
            section = m.group(1).title()
            subtitle = m.group(2).strip()
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                next_clean = _strip_tags(next_line)
                if next_clean and len(next_clean) < 40 and not _PART_RE.match(next_line):
                    subtitle += " " + next_clean
            full_title = f"{section}: {subtitle}"
            chapters.append(ChapterDef(title=full_title, start_line=i))
            i += 1
            continue

        i += 1

    # Fill in end_line for each chapter
    for j in range(len(chapters) - 1):
        chapters[j].end_line = chapters[j + 1].start_line

    if not artifact_level:
        return chapters

    # --- Artifact-level splitting: replace PART chapters with items ---
    toc_titles = _parse_toc_artifacts(lines, toc_end)
    max_artifact = max(toc_titles.keys()) if toc_titles else 0
    if not max_artifact:
        return chapters

    # Find body region: first PART start to first non-PART section after PARTs
    part_indices = [j for j, ch in enumerate(chapters) if ch.title.startswith("Part ")]
    if not part_indices:
        return chapters

    body_start = chapters[part_indices[0]].start_line
    body_end_idx = part_indices[-1] + 1
    body_end = chapters[body_end_idx].start_line if body_end_idx < len(chapters) else len(lines)

    boundaries = _find_artifact_boundaries(lines, body_start, body_end, max_artifact)

    # Build artifact chapters, sorted by start line
    artifact_chapters: list[ChapterDef] = []
    sorted_nums = sorted(boundaries.keys(), key=lambda n: boundaries[n])

    for k, num in enumerate(sorted_nums):
        title = toc_titles.get(num, f"Item {num}")
        full_title = f"{num}. {title}"
        start = boundaries[num]

        # end_line = start of next artifact or body_end
        if k + 1 < len(sorted_nums):
            end = boundaries[sorted_nums[k + 1]]
        else:
            end = body_end

        artifact_chapters.append(ChapterDef(title=full_title, start_line=start, end_line=end))

    # Check if PART intro text exists before first artifact
    first_artifact_start = boundaries[sorted_nums[0]] if sorted_nums else body_end
    for j in part_indices:
        part_ch = chapters[j]
        if part_ch.start_line < first_artifact_start:
            # Find next boundary after this PART
            next_start = body_end
            for num in sorted_nums:
                if boundaries[num] > part_ch.start_line:
                    next_start = boundaries[num]
                    break
            if next_start > part_ch.start_line:
                artifact_chapters.append(
                    ChapterDef(title=part_ch.title, start_line=part_ch.start_line, end_line=next_start)
                )

    # Sort all artifact chapters by start_line
    artifact_chapters.sort(key=lambda c: c.start_line)

    # Replace PART chapters with artifact chapters in the final list
    result: list[ChapterDef] = []
    for ch in chapters:
        if ch.title.startswith("Part "):
            continue
        result.append(ch)

    # Insert artifact chapters at the right position
    combined = result + artifact_chapters
    combined.sort(key=lambda c: c.start_line)

    # Re-fill end_line for non-artifact chapters
    for j in range(len(combined) - 1):
        if combined[j].end_line is None:
            combined[j].end_line = combined[j + 1].start_line
    # Last chapter: clear end_line (EOF)
    combined[-1].end_line = None

    return combined


def split_markdown(
    md_path: Path,
    output_dir: Path,
    chapter_defs: list[ChapterDef] | None = None,
    *,
    artifact_level: bool = False,
) -> list[Path]:
    """Split a single markdown file into per-chapter directories.

    If chapter_defs is None, auto-detects chapters from content.
    When *artifact_level* is True, splits within PART sections at
    individual numbered items.

    Directory naming:
    - With page ranges: NNN_pp_START_END_slug/
    - Without page ranges: NNN_slug/

    Returns list of created markdown file paths.
    """
    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )

    if chapter_defs is None:
        chapter_defs = detect_chapters(
            [l.rstrip("\n") for l in lines], artifact_level=artifact_level,
        )

    if not chapter_defs:
        return []

    created: list[Path] = []
    for idx, ch in enumerate(chapter_defs):
        end = ch.end_line if ch.end_line is not None else len(lines)
        content = "".join(lines[ch.start_line : end])

        slug = slugify(ch.title)
        prefix = f"{(idx + 1) * 10:03d}"

        if ch.page_start is not None and ch.page_end is not None:
            dir_name = f"{prefix}_pp_{ch.page_start}_{ch.page_end}_{slug}"
        else:
            dir_name = f"{prefix}_{slug}"

        chapter_dir = output_dir / dir_name
        chapter_dir.mkdir(parents=True, exist_ok=True)

        filename = f"chapter_01_{slug}.md"
        out_path = chapter_dir / filename
        out_path.write_text(content, encoding="utf-8")
        created.append(out_path)

    return created
