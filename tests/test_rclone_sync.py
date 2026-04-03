"""Tests for rclone sync wrapper."""

from pathlib import Path
from unittest.mock import patch

import pytest

from doc2md.ingest.rclone_sync import RcloneError, sync


class TestRcloneSync:
    @patch("doc2md.ingest.rclone_sync.subprocess.run")
    def test_successful_sync(self, mock_run, tmp_path):
        mock_run.return_value = type("Result", (), {"returncode": 0, "stderr": ""})()
        local_dir = tmp_path / "synced"
        result = sync("gdrive:Books", local_dir, flags=["--progress"])
        assert result == local_dir
        assert local_dir.exists()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "rclone"
        assert "gdrive:Books" in cmd
        assert "--progress" in cmd

    @patch("doc2md.ingest.rclone_sync.subprocess.run")
    def test_failed_sync_raises(self, mock_run, tmp_path):
        mock_run.return_value = type("Result", (), {"returncode": 1, "stderr": "auth failed"})()
        with pytest.raises(RcloneError, match="auth failed"):
            sync("bad:remote", tmp_path / "out")

    @patch("doc2md.ingest.rclone_sync.subprocess.run")
    def test_no_flags(self, mock_run, tmp_path):
        mock_run.return_value = type("Result", (), {"returncode": 0, "stderr": ""})()
        sync("remote:path", tmp_path / "out")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["rclone", "sync", "remote:path", str(tmp_path / "out")]

    @patch("doc2md.ingest.rclone_sync.subprocess.run")
    def test_creates_local_dir(self, mock_run, tmp_path):
        mock_run.return_value = type("Result", (), {"returncode": 0, "stderr": ""})()
        local_dir = tmp_path / "deep" / "nested" / "dir"
        sync("remote:path", local_dir)
        assert local_dir.exists()
