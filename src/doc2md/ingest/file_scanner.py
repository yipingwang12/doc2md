"""Discover PDFs and screenshot folders for processing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScanResult:
    pdfs: list[Path]
    screenshot_folders: list[Path]


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}


def is_screenshot_folder(folder: Path) -> bool:
    """Check if a folder contains image files (likely screenshots)."""
    if not folder.is_dir():
        return False
    return any(f.suffix.lower() in IMAGE_EXTS for f in folder.iterdir() if f.is_file())


def scan_directories(dirs: list[str | Path]) -> ScanResult:
    """Scan directories for PDFs and screenshot folders."""
    pdfs = []
    screenshot_folders = []

    for d in dirs:
        path = Path(d).expanduser().resolve()
        if not path.exists():
            continue

        if path.is_file() and path.suffix.lower() == ".pdf":
            pdfs.append(path)
            continue

        if not path.is_dir():
            continue

        for item in sorted(path.iterdir()):
            if item.is_file() and item.suffix.lower() == ".pdf":
                pdfs.append(item)
            elif item.is_dir() and is_screenshot_folder(item):
                screenshot_folders.append(item)

    return ScanResult(pdfs=pdfs, screenshot_folders=screenshot_folders)
