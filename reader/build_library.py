#!/usr/bin/env python3
"""Scan results/ directories and generate library.json for the reader."""

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


def extract_title(md_path: Path) -> str | None:
    """Extract the first # heading from a markdown file."""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# ") and not line.startswith("## "):
                    return line[2:].strip()
    except (OSError, UnicodeDecodeError):
        return None
    return None


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

        for chapter_dir in sorted(volume_dir.iterdir()):
            if not chapter_dir.is_dir() or chapter_dir.name.startswith("."):
                continue

            if chapter_dir.name in SKIP_DIRS:
                continue

            md_files = sorted(chapter_dir.glob("chapter_*.md"))
            if not md_files:
                continue

            md_file = md_files[0]
            title = extract_title(md_file)

            if not title:
                title = prettify_dir_name(chapter_dir.name)

            rel_path = md_file.relative_to(results_dir.parent)

            words = count_body_words(md_file)
            chapters.append({
                "id": chapter_dir.name,
                "title": title,
                "path": str(rel_path),
                "words": words,
            })

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
