"""Resumability cache using a JSON manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class Cache:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.manifest_path = self.cache_dir / "manifest.json"
        self.intermediate_dir = self.cache_dir / "intermediate"
        self._manifest: dict = self._load()

    def _load(self) -> dict:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return {"files": {}}

    def _save(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self._manifest, indent=2))

    @staticmethod
    def file_hash(path: Path) -> str:
        h = hashlib.sha256()
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    h.update(str(f.relative_to(path)).encode())
                    h.update(str(f.stat().st_size).encode())
            return h.hexdigest()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def is_complete(self, file_path: Path) -> bool:
        key = str(file_path.resolve())
        entry = self._manifest["files"].get(key)
        if entry is None:
            return False
        current_hash = self.file_hash(file_path)
        if entry["file_hash"] != current_hash:
            return False
        return "assemble" in entry.get("stages_completed", [])

    def get_completed_stages(self, file_path: Path) -> list[str]:
        key = str(file_path.resolve())
        entry = self._manifest["files"].get(key)
        if entry is None:
            return []
        current_hash = self.file_hash(file_path)
        if entry["file_hash"] != current_hash:
            return []
        return entry.get("stages_completed", [])

    def mark_stage(self, file_path: Path, stage: str, output_path: str | None = None):
        key = str(file_path.resolve())
        entry = self._manifest["files"].setdefault(key, {
            "file_hash": self.file_hash(file_path),
            "stages_completed": [],
            "output_path": None,
            "last_processed": None,
        })
        entry["file_hash"] = self.file_hash(file_path)
        if stage not in entry["stages_completed"]:
            entry["stages_completed"].append(stage)
        if output_path:
            entry["output_path"] = output_path
        entry["last_processed"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def clear(self):
        self._manifest = {"files": {}}
        if self.manifest_path.exists():
            self.manifest_path.unlink()

    def status(self) -> dict[str, list[str]]:
        return {k: v.get("stages_completed", []) for k, v in self._manifest["files"].items()}
