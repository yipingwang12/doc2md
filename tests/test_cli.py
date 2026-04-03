"""Tests for CLI commands."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from doc2md.cli import main


class TestCli:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "doc2md" in result.output

    @patch("doc2md.ingest.rclone_sync.sync")
    def test_sync_command(self, mock_sync, tmp_path):
        mock_sync.return_value = tmp_path
        runner = CliRunner()
        result = runner.invoke(main, ["sync"])
        assert result.exit_code == 0
        assert "Synced" in result.output

    def test_status_empty(self, tmp_path):
        runner = CliRunner()
        config_file = tmp_path / "config.toml"
        config_file.write_text(f'[paths]\ncache_dir = "{tmp_path}/cache"\n')
        result = runner.invoke(main, ["--config", str(config_file), "status"])
        assert result.exit_code == 0
        assert "No files processed" in result.output

    def test_clean_command(self, tmp_path):
        runner = CliRunner()
        config_file = tmp_path / "config.toml"
        config_file.write_text(f'[paths]\ncache_dir = "{tmp_path}/cache"\n')
        result = runner.invoke(main, ["--config", str(config_file), "clean"])
        assert result.exit_code == 0
        assert "Cache cleared" in result.output

    @patch("doc2md.pipeline.process_file")
    def test_process_command(self, mock_process, tmp_path):
        mock_process.return_value = [tmp_path / "output.md"]
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"dummy")
        runner = CliRunner()
        result = runner.invoke(main, ["process", str(test_file)])
        assert result.exit_code == 0
        assert "Processing" in result.output
