"""Tests for file discovery."""

from doc2md.ingest.file_scanner import is_screenshot_folder, scan_directories


class TestIsScreenshotFolder:
    def test_folder_with_images(self, tmp_path):
        folder = tmp_path / "book1"
        folder.mkdir()
        (folder / "page1.png").write_bytes(b"fake")
        assert is_screenshot_folder(folder) is True

    def test_folder_without_images(self, tmp_path):
        folder = tmp_path / "empty"
        folder.mkdir()
        (folder / "notes.txt").write_text("text")
        assert is_screenshot_folder(folder) is False

    def test_not_a_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("text")
        assert is_screenshot_folder(f) is False


class TestScanDirectories:
    def test_finds_pdfs(self, tmp_path):
        (tmp_path / "paper.pdf").write_bytes(b"fake")
        (tmp_path / "readme.txt").write_text("ignore")
        result = scan_directories([tmp_path])
        assert len(result.pdfs) == 1
        assert result.pdfs[0].name == "paper.pdf"

    def test_finds_screenshot_folders(self, tmp_path):
        book = tmp_path / "my_book"
        book.mkdir()
        (book / "page1.jpg").write_bytes(b"fake")
        result = scan_directories([tmp_path])
        assert len(result.screenshot_folders) == 1

    def test_handles_nonexistent_dirs(self):
        result = scan_directories(["/nonexistent/path"])
        assert result.pdfs == []
        assert result.screenshot_folders == []

    def test_single_pdf_file(self, tmp_path):
        pdf = tmp_path / "single.pdf"
        pdf.write_bytes(b"fake")
        result = scan_directories([pdf])
        assert len(result.pdfs) == 1

    def test_mixed_content(self, tmp_path):
        (tmp_path / "paper.pdf").write_bytes(b"fake")
        book = tmp_path / "book1"
        book.mkdir()
        (book / "s1.png").write_bytes(b"fake")
        result = scan_directories([tmp_path])
        assert len(result.pdfs) == 1
        assert len(result.screenshot_folders) == 1
