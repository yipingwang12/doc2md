"""Tests for cache/resumability."""

import json

from doc2md.cache import Cache


class TestCache:
    def test_empty_cache(self, tmp_cache):
        cache = Cache(tmp_cache)
        assert cache.status() == {}

    def test_mark_stage(self, tmp_cache, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"pdf content")
        cache = Cache(tmp_cache)
        cache.mark_stage(test_file, "extract")
        stages = cache.get_completed_stages(test_file)
        assert "extract" in stages

    def test_is_complete_requires_assemble(self, tmp_cache, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"pdf content")
        cache = Cache(tmp_cache)
        cache.mark_stage(test_file, "extract")
        assert not cache.is_complete(test_file)
        cache.mark_stage(test_file, "assemble")
        assert cache.is_complete(test_file)

    def test_file_change_invalidates_cache(self, tmp_cache, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"original")
        cache = Cache(tmp_cache)
        cache.mark_stage(test_file, "extract")
        cache.mark_stage(test_file, "assemble")
        assert cache.is_complete(test_file)

        test_file.write_bytes(b"modified")
        assert not cache.is_complete(test_file)

    def test_clear(self, tmp_cache, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"content")
        cache = Cache(tmp_cache)
        cache.mark_stage(test_file, "extract")
        cache.clear()
        assert cache.status() == {}

    def test_manifest_persists(self, tmp_cache, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"content")
        cache = Cache(tmp_cache)
        cache.mark_stage(test_file, "extract")

        cache2 = Cache(tmp_cache)
        assert "extract" in cache2.get_completed_stages(test_file)

    def test_duplicate_stage_not_added_twice(self, tmp_cache, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"content")
        cache = Cache(tmp_cache)
        cache.mark_stage(test_file, "extract")
        cache.mark_stage(test_file, "extract")
        stages = cache.get_completed_stages(test_file)
        assert stages.count("extract") == 1

    def test_output_path_stored(self, tmp_cache, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"content")
        cache = Cache(tmp_cache)
        cache.mark_stage(test_file, "assemble", output_path="results/ch01.md")
        manifest = json.loads(cache.manifest_path.read_text())
        key = str(test_file.resolve())
        assert manifest["files"][key]["output_path"] == "results/ch01.md"
