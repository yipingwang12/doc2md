"""Tests for configuration loading."""

from pathlib import Path

from doc2md.config import Config, load_config


class TestLoadConfig:
    def test_defaults_when_no_file(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.toml")
        assert isinstance(config, Config)
        assert config.llm.model == "llama3.1:8b"
        assert config.extraction.pymupdf_min_chars == 100

    def test_loads_from_toml(self, sample_config_toml):
        config = load_config(sample_config_toml)
        assert config.paths.google_drive_remote == "test:Remote"
        assert config.paths.local_pdf_dirs == ["/tmp/pdfs"]
        assert config.paths.output_dir == "./test_output"
        assert config.llm.model == "llama3.1:8b"
        assert config.llm.timeout == 60
        assert config.extraction.pymupdf_min_chars == 50

    def test_partial_config_uses_defaults(self, tmp_path):
        config_file = tmp_path / "partial.toml"
        config_file.write_text('[llm]\nmodel = "custom:7b"\n')
        config = load_config(config_file)
        assert config.llm.model == "custom:7b"
        assert config.llm.timeout == 120  # default
        assert config.paths.output_dir == "./results"  # default

    def test_unknown_keys_ignored(self, tmp_path):
        config_file = tmp_path / "extra.toml"
        config_file.write_text('[llm]\nmodel = "test"\nunknown_key = "val"\n')
        config = load_config(config_file)
        assert config.llm.model == "test"
