"""Google Drive sync via rclone subprocess."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class RcloneError(Exception):
    pass


def sync(remote: str, local_dir: Path, flags: list[str] | None = None) -> Path:
    """Sync a remote rclone path to a local directory.

    Returns the local directory path.
    """
    local_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["rclone", "sync", remote, str(local_dir)]
    if flags:
        cmd.extend(flags)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RcloneError(f"rclone sync failed: {result.stderr}")

    return local_dir
