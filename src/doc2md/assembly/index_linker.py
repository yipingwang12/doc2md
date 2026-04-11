"""Link index entries to chapter files by page number matching."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageRef:
    start: int
    end: int | None = None

    def __eq__(self, other):
        if not isinstance(other, PageRef):
            return NotImplemented
        return self.start == other.start and self.end == other.end

    def label(self) -> str:
        if self.end is not None:
            return f"{self.start}–{self.end}"
        return str(self.start)


@dataclass
class IndexEntry:
    term: str
    page_refs: list[PageRef]
    sub_entries: list[IndexEntry] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class ChapterFile:
    dir_name: str
    page_start: int
    page_end: int
    md_paths: list[Path]
    text: str


# --- Pure helpers ---

def expand_abbreviated_end(start: int, abbrev_end: str) -> int:
    """Expand abbreviated page range end: (325, '31') -> 331."""
    s = str(start)
    if len(abbrev_end) >= len(s):
        return int(abbrev_end)
    prefix = s[: len(s) - len(abbrev_end)]
    return int(prefix + abbrev_end)


_REF_RE = re.compile(r"(\d+)\s*[–\-]\s*(\d+)|(\d+)")


def parse_page_refs(text: str) -> list[PageRef]:
    """Parse comma-separated page references like '241, 316–31, 455'."""
    refs = []
    for m in _REF_RE.finditer(text):
        if m.group(1) and m.group(2):
            start = int(m.group(1))
            end = expand_abbreviated_end(start, m.group(2))
            refs.append(PageRef(start, end))
        elif m.group(3):
            refs.append(PageRef(int(m.group(3))))
    return refs


# --- Index parsing ---

_PAGE_HEADING_RE = re.compile(r"^#{1,4}\s+\d+\s*$")
_NB_RE = re.compile(r"^N\.B\..*$", re.IGNORECASE)
_SEE_ALSO_RE = re.compile(r"See also\s*(.*)$", re.IGNORECASE)
_SEE_RE = re.compile(r"^.*\.\s*See\s+(.+)$", re.IGNORECASE)
_CONT_RE = re.compile(r"^(.+?)\s*\(cont\.\)\s*$")
_TRAILING_REFS_RE = re.compile(r",?\s*((?:\d+[–\-]?\d*(?:,\s*)?)+)\s*$")


def _split_term_and_refs(line: str) -> tuple[str, str]:
    """Split 'abacus, 516–17' into ('abacus', '516–17')."""
    m = _TRAILING_REFS_RE.search(line)
    if m:
        term = line[: m.start()].rstrip(", ")
        return term, m.group(1)
    return line.rstrip(", "), ""


def _is_sub_entry(line: str) -> bool:
    """Heuristic: sub-entries start with lowercase or known patterns."""
    if not line:
        return False
    return line[0].islower() or line[0] == '"'


_BIBLIO_START_RE = re.compile(r"^\[\^\d+\]:|^\d{4}\s+[A-Z]")


def parse_index_md(text: str) -> list[IndexEntry]:
    """Parse index markdown into structured entries."""
    lines = text.splitlines()
    entries: list[IndexEntry] = []
    current: IndexEntry | None = None
    prev_blank = False

    for line in lines:
        stripped = line.strip()

        # Double blank line or bibliography entry signals end of index
        if not stripped:
            if prev_blank and entries:
                break
            prev_blank = True
            continue
        if _BIBLIO_START_RE.match(stripped) and entries:
            break
        prev_blank = False

        # Skip headings, page-number headings, NB notes
        if stripped.startswith("#"):
            if _PAGE_HEADING_RE.match(stripped):
                continue
            continue
        if _NB_RE.match(stripped):
            continue

        # Handle "See also X" on its own line or at end of entry
        see_also_m = _SEE_ALSO_RE.match(stripped)
        if see_also_m and current:
            targets = see_also_m.group(1).strip()
            if targets:
                current.see_also.append(targets)
            # If empty (targets on next line), set flag via empty marker
            else:
                current.see_also.append("")
            continue

        # Handle "(term) (cont.)" — continuation of a previous main entry
        cont_m = _CONT_RE.match(stripped)
        if cont_m:
            cont_term = cont_m.group(1).strip()
            for e in entries:
                if e.term.lower() == cont_term.lower():
                    current = e
                    break
            else:
                current = IndexEntry(cont_term, [], [], [], stripped)
                entries.append(current)
            continue

        # Handle "See also" continuation: previous line was "See also"
        # with empty target, this line has the actual targets
        if current and current.see_also and current.see_also[-1] == "":
            current.see_also[-1] = stripped
            continue

        # Strip inline ". See also [targets]" from entry lines.
        # Targets may be on this line or the next; extracted into see_also.
        pending_see_also = False
        see_also_trail = re.search(r"[.;]\s*See also\s*(.*?)\s*$", stripped, re.IGNORECASE)
        if see_also_trail:
            stripped = stripped[: see_also_trail.start()].rstrip()
            targets = see_also_trail.group(1).strip()
            pending_see_also = True
            _pending_see_also_targets = targets if targets else ""

        # Handle "See X" (not "See also") — e.g. "Alhacen. See Ibn al-Haytham"
        see_m = _SEE_RE.match(stripped)
        if see_m and not see_also_m:
            captured = see_m.group(1).strip()
            if captured.lower().startswith("also"):
                # "See also X" caught by _SEE_RE — extract targets
                pending_see_also = True
                _pending_see_also_targets = captured[5:].strip() if len(captured) > 5 else ""
            else:
                term_part = stripped.split(". See")[0].rstrip()
                term, ref_text = _split_term_and_refs(term_part)
                entry = IndexEntry(
                    term=term or stripped,
                    page_refs=parse_page_refs(ref_text),
                    see_also=[captured],
                    raw_text=stripped,
                )
                entries.append(entry)
                current = entry
                if pending_see_also:
                    current.see_also.append("")
                continue

        # Check if this is a page-ref continuation line (starts with digit)
        if stripped[0].isdigit() and current:
            new_refs = parse_page_refs(stripped)
            if current.sub_entries:
                current.sub_entries[-1].page_refs.extend(new_refs)
            else:
                current.page_refs.extend(new_refs)
            current.raw_text += "\n" + stripped
            if pending_see_also:
                current.see_also.append(_pending_see_also_targets)
            continue

        # Check if this is a wrapped text continuation.
        # A line is a continuation when the previous raw_text ends
        # mid-phrase: after a semicolon sub-topic separator, after a
        # comma, or with a word fragment that isn't a page reference.
        if current:
            prev_raw = current.raw_text.rstrip()
            # Get the last raw line (for multi-line entries)
            prev_last = prev_raw.split("\n")[-1].rstrip()
            # A line wraps when it ends mid-phrase:
            # - ends with comma or semicolon, OR
            # - ends with a word AND the line contains page refs
            #   (distinguishes "...146; in Native" from "Albertus Magnus")
            has_refs_on_line = bool(re.search(r"\d", prev_last))
            is_continuation = (
                prev_last.endswith(",")
                or prev_last.endswith(";")
                or (has_refs_on_line and re.search(r"[a-zA-Z]$", prev_last) is not None)
            )
            if is_continuation:
                term, ref_text = _split_term_and_refs(stripped)
                refs = parse_page_refs(ref_text)
                if current.sub_entries:
                    last = current.sub_entries[-1]
                    last.term += " " + term
                    last.page_refs.extend(refs)
                    last.raw_text += "\n" + stripped
                else:
                    current.term += " " + term
                    current.page_refs.extend(refs)
                current.raw_text += "\n" + stripped
                continue

        # Sub-entry or new main entry?
        term, ref_text = _split_term_and_refs(stripped)
        refs = parse_page_refs(ref_text)

        if current and _is_sub_entry(stripped):
            sub = IndexEntry(term=term, page_refs=refs, raw_text=stripped)
            current.sub_entries.append(sub)
        else:
            entry = IndexEntry(term=term, page_refs=refs, raw_text=stripped)
            entries.append(entry)
            current = entry

        if pending_see_also and current:
            current.see_also.append(_pending_see_also_targets)

    return entries


# --- Chapter map ---

_PP_RE = re.compile(r"_pp_(\d+)_(\d+)_")


def build_chapter_map(volume_dir: Path) -> list[ChapterFile]:
    """Build sorted list of chapters from volume output directory."""
    chapters = []
    for d in sorted(volume_dir.iterdir()):
        if not d.is_dir():
            continue
        if "index" in d.name.lower():
            continue
        m = _PP_RE.search(d.name)
        if not m:
            continue
        try:
            start = int(m.group(1))
            end = int(m.group(2))
        except ValueError:
            continue

        md_files = sorted(d.glob("chapter_*.md"))
        if not md_files:
            continue

        text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in md_files)
        chapters.append(ChapterFile(d.name, start, end, md_files, text))

    chapters.sort(key=lambda c: c.page_start)
    return chapters


def build_chapter_map_pageless(volume_dir: Path) -> list[ChapterFile]:
    """Build chapter list without requiring _pp_ page ranges in dir names.

    Used for books (e.g. Libby screenshots) where physical page numbers
    are unavailable. Sets page_start=0, page_end=0 since page ranges
    are unused in pageless linking mode.
    """
    chapters = []
    for d in sorted(volume_dir.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith(".") or d.name.endswith(".orig"):
            continue
        if "index" in d.name.lower():
            continue

        md_files = sorted(d.glob("chapter_*.md"))
        if not md_files:
            continue

        text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in md_files)
        chapters.append(ChapterFile(d.name, 0, 0, md_files, text))

    return chapters


def find_chapter_for_page(page: int, chapters: list[ChapterFile]) -> ChapterFile | None:
    """Return the chapter whose page range contains the given page.

    When multiple chapters overlap (e.g. section divider covering pages
    149-822 alongside individual chapters), prefer the narrowest range.
    """
    best = None
    best_span = float("inf")
    for ch in chapters:
        if ch.page_start <= page <= ch.page_end:
            span = ch.page_end - ch.page_start
            if span < best_span:
                best = ch
                best_span = span
    return best


# --- Rendering ---

def _md_path_for_chapter(ch: ChapterFile) -> str:
    """Get the primary .md filename for linking."""
    if ch.md_paths:
        return ch.md_paths[-1].name
    return "chapter_01_.md"


_TAG_STRIP_RE = re.compile(r"</?(?:b|i|math|sup|a)[^>]*>")
_PAREN_RE = re.compile(r"\s*\([^)]*\)")


def _term_variants(term: str) -> list[str]:
    """Generate search variants for an index term.

    'Abelard, Peter' -> ['abelard, peter', 'peter abelard', 'abelard']
    'medicine in Africa' -> ['medicine in africa', 'medicine', 'africa']
    'AMS (accelerated mass spectrometer) dating' -> [..., 'ams dating']
    'Beacon Hill: as fashionable neighborhood' -> [..., 'beacon hill']
    '<b>Boston Town Records</b>' -> [..., 'boston town records']
    """
    # Strip HTML tags first
    cleaned = _TAG_STRIP_RE.sub("", term).strip()
    low = cleaned.lower().strip()
    variants = [low]

    # "Last, First" -> "First Last"
    if ", " in low:
        parts = low.split(", ", 1)
        variants.append(f"{parts[1]} {parts[0]}")
        variants.append(parts[0])

    # Strip parenthetical qualifiers: "AMS (accelerated mass spectrometer) dating" -> "ams dating"
    if "(" in low:
        no_parens = _PAREN_RE.sub("", low).strip()
        if no_parens and no_parens != low:
            variants.append(no_parens)

    # Strip after colon/semicolon: "Beacon Hill: as fashionable..." -> "beacon hill"
    for sep in (":", ";"):
        if sep in low:
            base = low.split(sep, 1)[0].strip().rstrip(",")
            if base and base != low:
                variants.append(base)
            break

    # Drop trailing preposition phrases for matching
    words = low.split()
    if len(words) > 2:
        for prep in ("in", "of", "and", "the", "on", "at", "for", "from"):
            if prep in words[1:]:
                idx = words.index(prep, 1)
                variants.append(" ".join(words[:idx]))
                break
    return variants


def _term_in_chapter(term: str, ch: ChapterFile) -> bool:
    """Check if any variant of the term appears in the chapter text."""
    text_lower = ch.text.lower()
    return any(v in text_lower for v in _term_variants(term))


def _render_ref(ref: PageRef, term: str, chapters: list[ChapterFile], index_dir: str) -> str:
    """Render a single page ref as a link or plain text."""
    ch = find_chapter_for_page(ref.start, chapters)
    if ch and _term_in_chapter(term, ch):
        md_file = _md_path_for_chapter(ch)
        rel = f"../{ch.dir_name}/{md_file}"
        return f"[{ref.label()}]({rel})"
    return ref.label()


def _render_entry(entry: IndexEntry, chapters: list[ChapterFile], index_dir: str) -> str:
    """Render an IndexEntry with links."""
    if not entry.page_refs and not entry.sub_entries and not entry.see_also:
        return entry.raw_text or entry.term

    parts = [entry.term]

    if entry.page_refs:
        ref_strs = [_render_ref(r, entry.term, chapters, index_dir) for r in entry.page_refs]
        parts.append(", " + ", ".join(ref_strs))
        any_linked = any("[" in s for s in ref_strs)
    else:
        any_linked = False

    lines = [_join_parts(parts)]

    for sub in entry.sub_entries:
        sub_parts = [sub.term]
        if sub.page_refs:
            # Use parent term + sub term for matching
            search_term = sub.term
            ref_strs = [_render_ref(r, search_term, chapters, index_dir) for r in sub.page_refs]
            linked = any("[" in s for s in ref_strs)
            if linked:
                sub_parts.append(", " + ", ".join(ref_strs))
                lines.append(_join_parts(sub_parts))
            else:
                lines.append(sub.raw_text or (sub.term + ", " + ", ".join(ref_strs)))
        else:
            lines.append(sub.raw_text or sub.term)

    see_targets = [s for s in entry.see_also if s]
    if see_targets:
        lines.append("See also " + ", ".join(see_targets))

    return "\n".join(lines)


def _join_parts(parts: list[str]) -> str:
    return "".join(parts)


def render_linked_index(
    entries: list[IndexEntry],
    chapters: list[ChapterFile],
    index_dir: str,
) -> str:
    """Render all index entries with markdown links."""
    rendered = ["# INDEX\n"]
    for entry in entries:
        rendered.append(_render_entry(entry, chapters, index_dir))
    return "\n".join(rendered) + "\n"


# --- Pageless rendering (term-only matching, no page ranges) ---


def _find_chapters_for_term(term: str, chapters: list[ChapterFile]) -> list[ChapterFile]:
    """Find all chapters containing any variant of the term."""
    return [ch for ch in chapters if _term_in_chapter(term, ch)]


def _render_entry_pageless(entry: IndexEntry, chapters: list[ChapterFile], index_dir: str) -> str:
    """Render an IndexEntry using term-only matching (no page ranges)."""
    if not entry.page_refs and not entry.sub_entries and not entry.see_also:
        return entry.raw_text or entry.term

    parts = [entry.term]
    matched = _find_chapters_for_term(entry.term, chapters)

    if matched:
        links = []
        for ch in matched:
            md_file = _md_path_for_chapter(ch)
            rel = f"../{ch.dir_name}/{md_file}"
            # Use chapter dir name as display text
            label = ch.dir_name.split("_", 1)[-1].replace("_", " ").strip()
            if not label:
                label = ch.dir_name
            links.append(f"[{label}]({rel})")
        parts.append(", " + ", ".join(links))
    elif entry.page_refs:
        ref_strs = [r.label() for r in entry.page_refs]
        parts.append(", " + ", ".join(ref_strs))

    lines = [_join_parts(parts)]

    for sub in entry.sub_entries:
        sub_matched = _find_chapters_for_term(sub.term, chapters)
        if sub_matched:
            sub_links = []
            for ch in sub_matched:
                md_file = _md_path_for_chapter(ch)
                rel = f"../{ch.dir_name}/{md_file}"
                label = ch.dir_name.split("_", 1)[-1].replace("_", " ").strip() or ch.dir_name
                sub_links.append(f"[{label}]({rel})")
            lines.append(sub.term + ", " + ", ".join(sub_links))
        else:
            lines.append(sub.raw_text or sub.term)

    see_targets = [s for s in entry.see_also if s]
    if see_targets:
        lines.append("See also " + ", ".join(see_targets))

    return "\n".join(lines)


def render_linked_index_pageless(
    entries: list[IndexEntry],
    chapters: list[ChapterFile],
    index_dir: str,
) -> str:
    """Render all index entries with term-only matching (no page ranges)."""
    rendered = ["# INDEX\n"]
    for entry in entries:
        rendered.append(_render_entry_pageless(entry, chapters, index_dir))
    return "\n".join(rendered) + "\n"


# --- Orchestrator ---

_INDEX_DIR_RE = re.compile(r"index", re.IGNORECASE)


def _find_index_file(volume_dir: Path) -> Path | None:
    """Find the index markdown file in a volume directory."""
    for d in sorted(volume_dir.iterdir()):
        if not d.is_dir():
            continue
        if "index" not in d.name.lower():
            continue
        for md in sorted(d.glob("chapter_*index*.md")):
            return md
        # Dir name contains "index" — take the last (largest) md file
        md_files = sorted(d.glob("chapter_*.md"))
        if md_files:
            return md_files[-1]
    return None


def link_index(volume_dir: Path) -> Path | None:
    """Link index entries to chapter files in a volume output directory.

    Uses page-range mode when directories have _pp_START_END_ naming.
    Falls back to pageless term-only matching when no page ranges found.

    Saves the original index as .orig.md on first run. Subsequent runs
    always read from .orig.md to avoid corruption from re-parsing
    linked output.

    Returns path to updated index file, or None if no index found
    or no chapters available.
    """
    chapters = build_chapter_map(volume_dir)
    pageless = False
    if not chapters:
        chapters = build_chapter_map_pageless(volume_dir)
        pageless = True
    if not chapters:
        return None

    index_file = _find_index_file(volume_dir)
    if not index_file:
        return None

    orig_file = index_file.with_suffix(".orig.md")
    if not orig_file.exists():
        orig_file.write_text(
            index_file.read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )

    text = orig_file.read_text(encoding="utf-8", errors="replace")
    entries = parse_index_md(text)
    if not entries:
        return None

    if pageless:
        linked = render_linked_index_pageless(entries, chapters, index_file.parent.name)
    else:
        linked = render_linked_index(entries, chapters, index_file.parent.name)
    index_file.write_text(linked, encoding="utf-8")
    return index_file
