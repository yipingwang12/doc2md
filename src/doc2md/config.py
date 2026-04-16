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
class PubTatorConfig:
    base_url: str = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
    rate_limit_delay: float = 0.34  # ~3 req/s NCBI limit
    pubtator_sections: list[str] = field(default_factory=lambda: ["abstract"])


@dataclass
class Bern2Config:
    base_url: str = "http://bern2.korea.ac.kr"
    timeout: int = 60


@dataclass
class PapersConfig:
    papers_dir: str = "./results/papers"
    entity_types: list[str] = field(default_factory=lambda: [
        "gene", "disease", "chemical", "species", "variant", "cell_line", "cell_type"
    ])
    pubtator: PubTatorConfig = field(default_factory=PubTatorConfig)
    bern2: Bern2Config = field(default_factory=Bern2Config)


@dataclass
class Config:
    paths: PathsConfig = field(default_factory=PathsConfig)
    rclone: RcloneConfig = field(default_factory=RcloneConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    papers: PapersConfig = field(default_factory=PapersConfig)


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

    if "papers" in data:
        papers_data = data["papers"]
        for k, v in papers_data.items():
            if k == "pubtator":
                for pk, pv in v.items():
                    if hasattr(config.papers.pubtator, pk):
                        setattr(config.papers.pubtator, pk, pv)
            elif k == "bern2":
                for bk, bv in v.items():
                    if hasattr(config.papers.bern2, bk):
                        setattr(config.papers.bern2, bk, bv)
            elif hasattr(config.papers, k):
                setattr(config.papers, k, v)

    return config
