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


class TestPapersCli:
    def test_papers_group_exists(self):
        runner = CliRunner()
        result = runner.invoke(main, ["papers", "--help"])
        assert result.exit_code == 0
        assert "process" in result.output
        assert "build-index" in result.output
        assert "search-entity" in result.output

    @patch("doc2md.papers.pipeline.process_paper")
    def test_papers_process(self, mock_proc, tmp_path):
        mock_proc.return_value = [tmp_path / "paper.md"]
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"dummy")
        runner = CliRunner()
        result = runner.invoke(main, ["papers", "process", str(pdf)])
        assert result.exit_code == 0
        assert "Processing paper" in result.output
        mock_proc.assert_called_once()

    @patch("doc2md.papers.pipeline.process_paper")
    def test_papers_process_with_pmid(self, mock_proc, tmp_path):
        mock_proc.return_value = []
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"dummy")
        runner = CliRunner()
        runner.invoke(main, ["papers", "process", str(pdf), "--pmid", "12345678"])
        assert mock_proc.call_args[1]["pmid"] == "12345678"

    def test_papers_build_index(self, tmp_path):
        import json
        papers_dir = tmp_path / "papers"
        paper_dir = papers_dir / "smith_2024"
        paper_dir.mkdir(parents=True)
        (paper_dir / "entities.json").write_text(json.dumps([{
            "text": "BRCA1", "entity_type": "gene", "entity_id": "NCBIGene:672",
            "source": "pubtator", "section_label": "abstract",
            "start": 0, "end": 5, "context": "BRCA1 is important.",
        }]))
        runner = CliRunner()
        result = runner.invoke(main, ["papers", "build-index", "--papers-dir", str(papers_dir)])
        assert result.exit_code == 0
        assert "1 entities" in result.output
        assert (papers_dir / "entity_index.json").exists()

    def test_papers_search_entity_found(self, tmp_path):
        import json
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        index = {
            "NCBIGene:672": {
                "entity_id": "NCBIGene:672", "entity_type": "gene",
                "display_name": "BRCA1",
                "occurrences": [{"paper_source": "smith_2024", "section": "abstract",
                                  "context": "BRCA1 is important."}],
            }
        }
        (papers_dir / "entity_index.json").write_text(json.dumps(index))
        runner = CliRunner()
        result = runner.invoke(main, [
            "papers", "search-entity", "BRCA1",
            "--index", str(papers_dir / "entity_index.json"),
        ])
        assert result.exit_code == 0
        assert "BRCA1" in result.output
        assert "smith_2024" in result.output

    def test_papers_search_entity_not_found(self, tmp_path):
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        (papers_dir / "entity_index.json").write_text("{}")
        runner = CliRunner()
        result = runner.invoke(main, [
            "papers", "search-entity", "TP53",
            "--index", str(papers_dir / "entity_index.json"),
        ])
        assert result.exit_code == 0
        assert "No entities found" in result.output
