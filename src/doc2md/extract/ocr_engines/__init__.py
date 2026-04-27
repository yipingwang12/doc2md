"""Pluggable OCR engines behind a common protocol."""

from doc2md.extract.ocr_engines.apple_vision import AppleVisionEngine
from doc2md.extract.ocr_engines.base import OcrEngine, OcrResult
from doc2md.extract.ocr_engines.cascade import (
    CascadeEngine,
    QualityCheck,
    build_default_cascade,
    default_quality_check,
)
from doc2md.extract.ocr_engines.claude_api import ClaudeApiEngine, quality_ok as claude_quality_ok
from doc2md.extract.ocr_engines.surya import SuryaEngine
from doc2md.extract.ocr_engines.tesseract import TesseractEngine

__all__ = [
    "OcrEngine",
    "OcrResult",
    "QualityCheck",
    "SuryaEngine",
    "TesseractEngine",
    "AppleVisionEngine",
    "CascadeEngine",
    "ClaudeApiEngine",
    "claude_quality_ok",
    "default_quality_check",
    "build_default_cascade",
]
