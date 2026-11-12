from types import SimpleNamespace

import numpy as np

from va_lab.ocr import OCR


def test_uncertain_latin_text_uses_more_confident_english_result():
    ocr = OCR.__new__(OCR)
    points = [[10, 10], [90, 10], [90, 30], [10, 30]]
    ocr.reader = SimpleNamespace(readtext=lambda *_, **__: [(points, "V|SION", 0.3)])
    ocr.english = SimpleNamespace(recognize=lambda *_, **__: [(points, "VISION", 0.99)])
    result = ocr.read(np.full((60, 100, 3), 255, np.uint8))
    assert result == [((10.0, 10.0, 90.0, 30.0), "VISION", 0.99)]


def test_bengali_text_is_not_replaced_by_english_hallucination():
    ocr = OCR.__new__(OCR)
    points = [[10, 10], [90, 10], [90, 30], [10, 30]]
    ocr.reader = SimpleNamespace(readtext=lambda *_, **__: [(points, "চেয়ার", 0.6)])
    def wrong_reader(*_, **__):
        raise AssertionError("English recognizer must not run for Bengali text")
    ocr.english = SimpleNamespace(recognize=wrong_reader)
    result = ocr.read(np.full((60, 100, 3), 255, np.uint8))
    assert result[0][1] == "চেয়ার"
