#!/usr/bin/env python3
"""Scan results/ directories and generate library.json for the reader."""

import hashlib
import json
import re
from pathlib import Path

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
DEFAULT_OUTPUT_FILE = Path(__file__).resolve().parent.parent / "library.json"

VOLUME_TITLES = {
    "cambridge_science_v1": "Cambridge History of Science Vol. 1: Ancient Science",
    "cambridge_science_v2": "Cambridge History of Science Vol. 2: Medieval Science",
    "cambridge_science_v3": "Cambridge History of Science Vol. 3: Early Modern Science",
    "cambridge_science_v4": "Cambridge History of Science Vol. 4: Eighteenth-Century Science",
    "cambridge_science_v5": "Cambridge History of Science Vol. 5: Modern Physical & Mathematical Sciences",
    "cambridge_science_v6": "Cambridge History of Science Vol. 6: Modern Biological & Earth Sciences",
    "cambridge_science_v7": "Cambridge History of Science Vol. 7: Modern Social Sciences",
    "cambridge_science_v8": "Cambridge History of Science Vol. 8: Modern Science in National, Transnational, & Global Context",
}

SKIP_DIRS = {
    "acknowledgments", "contents", "copyright_page", "general_editors_preface",
    "illustrations", "index", "notes_on_contributors",
}

# Substrings in directory names that indicate non-content (metadata) chapters
_SKIP_SUBSTRINGS = [
    "frontmatter", "copyright", "contents", "illustrations",
    "notes_on_contributors", "general_editors_preface", "acknowledgments",
]



def extract_yaml_front_matter(md_path: Path) -> dict:
    """Parse YAML front matter from a markdown file.

    Handles scalar values and list values (lines starting with '  - ').
    Returns dict with any of: title, authors, journal, year, doi, pmid.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}

    result: dict = {}
    current_key = None
    for line in lines[1:end]:
        if line.startswith("  - "):
            if current_key is not None:
                if not isinstance(result.get(current_key), list):
                    result[current_key] = []
                result[current_key].append(line[4:].strip())
        elif ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            current_key = key
            if val:
                result[key] = val
            else:
                result[key] = []
    return result


def extract_title(md_path: Path) -> str | None:
    """Extract chapter title from a markdown file.

    Uses the first # heading unless it's just a number (e.g. "# 2"),
    in which case falls back to the first ### heading (the descriptive title
    in Cambridge UP PDFs). Joins continuation lines that follow a heading
    (e.g. "### THE LEGACY OF THE\\n\\"SCIENTIFIC REVOLUTION\\"").
    """
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return None
    h1 = None
    first_sub = None
    first_sub_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## ") and h1 is None:
            h1 = stripped[2:].strip()
        elif stripped.startswith("### ") and first_sub is None:
            first_sub = stripped[4:].strip()
            first_sub_idx = i
    # Join continuation lines after ### heading (all-caps non-blank, non-heading)
    if first_sub is not None and first_sub_idx is not None:
        for line in lines[first_sub_idx + 1:]:
            cont = line.strip()
            if not cont or cont.startswith("#"):
                break
            if cont == cont.upper() or cont.startswith('"'):
                first_sub += " " + cont
            else:
                break
    if h1 and not re.match(r"^\d+$", h1):
        return h1
    if first_sub:
        return first_sub
    return h1


def count_body_words(md_path: Path) -> int:
    """Count words in body text, excluding footnote definitions and references."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    fn_match = re.search(r"^\[\^\d+\]:", text, re.MULTILINE)
    body = text[:fn_match.start()] if fn_match else text
    ref_match = re.search(r"^## References\s*$", body, re.MULTILINE)
    if ref_match:
        body = body[:ref_match.start()]
    return len(body.split())


def prettify_dir_name(name: str) -> str:
    """Convert directory name to title case as fallback."""
    cleaned = re.sub(r"^\d+_pp_\d+_\d+_", "", name)
    cleaned = re.sub(r"^\d+_", "", cleaned)
    return cleaned.replace("_", " ").title()


def build_library(results_dir: Path = DEFAULT_RESULTS_DIR) -> dict:
    """Scan results_dir and return library dict."""
    books = []

    if not results_dir.exists():
        print(f"Warning: {results_dir} does not exist")
        return {"books": books}

    for volume_dir in sorted(results_dir.iterdir()):
        if not volume_dir.is_dir() or volume_dir.name.startswith("."):
            continue

        book_id = volume_dir.name
        book_title = VOLUME_TITLES.get(book_id, prettify_dir_name(book_id))
        chapters = []
        seen_hashes: set[str] = set()

        for chapter_dir in sorted(volume_dir.iterdir()):
            if not chapter_dir.is_dir() or chapter_dir.name.startswith(".") or chapter_dir.name.endswith(".orig"):
                continue

            if chapter_dir.name in SKIP_DIRS:
                continue
            if any(s in chapter_dir.name for s in _SKIP_SUBSTRINGS):
                continue

            md_files = sorted(chapter_dir.glob("chapter_*.md"))
            if not md_files:
                continue

            # Skip section divider PDFs that duplicate actual chapter content
            content = b"".join(f.read_bytes() for f in md_files)
            h = hashlib.sha256(content).hexdigest()
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            # When chapter detector splits a title page into
            # chapter_01_front_matter.md, get title from the content file
            # (chapter_02+) but include all files for reading.
            title_file = md_files[-1] if len(md_files) > 1 else md_files[0]

            paper_metadata = extract_yaml_front_matter(md_files[0])
            yaml_title = paper_metadata.get("title", "")
            if yaml_title == "Unknown":
                yaml_title = ""

            title = yaml_title or extract_title(title_file)
            if not title:
                title = prettify_dir_name(chapter_dir.name)

            rel_paths = [str(f.relative_to(results_dir.parent)) for f in md_files]

            words = sum(count_body_words(f) for f in md_files)
            entry: dict = {
                "id": chapter_dir.name,
                "title": title,
                "path": rel_paths[0],
                "paths": rel_paths if len(rel_paths) > 1 else None,
                "words": words,
            }
            if paper_metadata:
                entry["paper_metadata"] = paper_metadata
            chapters.append(entry)

        if chapters:
            book_words = sum(ch["words"] for ch in chapters)
            books.append({
                "id": book_id,
                "title": book_title,
                "chapters": chapters,
                "words": book_words,
            })

    return {"books": books}


def main():
    library = build_library()
    with open(DEFAULT_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(library, f, indent=2, ensure_ascii=False)

    total_chapters = sum(len(b["chapters"]) for b in library["books"])
    print(f"Generated {DEFAULT_OUTPUT_FILE}: {len(library['books'])} books, {total_chapters} chapters")


if __name__ == "__main__":
    main()
