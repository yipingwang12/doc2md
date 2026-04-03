"""Configuration loading from TOML with CLI overrides."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PathsConfig:
    google_drive_remote: str = "gdrive:Books/Libby"
    local_pdf_dirs: list[str] = field(default_factory=lambda: ["~/Papers", "~/Books"])
    output_dir: str = "./results"
    cache_dir: str = "./.doc2md_cache"


@dataclass
class RcloneConfig:
    flags: list[str] = field(default_factory=lambda: ["--progress", "--transfers=4"])


@dataclass
class LlmConfig:
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    timeout: int = 120
    max_retries: int = 3


@dataclass
class ExtractionConfig:
    pymupdf_min_chars: int = 100
    gibberish_threshold: float = 0.3


@dataclass
class ProcessingConfig:
    batch_size: int = 5


@dataclass
class Config:
    paths: PathsConfig = field(default_factory=PathsConfig)
    rclone: RcloneConfig = field(default_factory=RcloneConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML file, falling back to defaults."""
    if path is None:
        path = Path("config.toml")

    if not path.exists():
        return Config()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    config = Config()

    if "paths" in data:
        for k, v in data["paths"].items():
            if hasattr(config.paths, k):
                setattr(config.paths, k, v)

    if "rclone" in data:
        for k, v in data["rclone"].items():
            if hasattr(config.rclone, k):
                setattr(config.rclone, k, v)

    if "llm" in data:
        for k, v in data["llm"].items():
            if hasattr(config.llm, k):
                setattr(config.llm, k, v)

    if "extraction" in data:
        for k, v in data["extraction"].items():
            if hasattr(config.extraction, k):
                setattr(config.extraction, k, v)

    if "processing" in data:
        for k, v in data["processing"].items():
            if hasattr(config.processing, k):
                setattr(config.processing, k, v)

    return config
