"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_cache(tmp_path):
    return tmp_path / "cache"


@pytest.fixture
def sample_config_toml(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("""
[paths]
google_drive_remote = "test:Remote"
local_pdf_dirs = ["/tmp/pdfs"]
output_dir = "./test_output"
cache_dir = "./test_cache"

[llm]
model = "llama3.1:8b"
timeout = 60

[extraction]
pymupdf_min_chars = 50
""")
    return config
