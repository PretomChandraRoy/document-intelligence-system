"""OCR: image clean-up and text recognition on scans of known invoices."""
from PIL import Image

from app.pipeline.ocr import _deskew, ocr_image, preprocess
from tests.helpers import norm


def test_clean_scan_reads_invoice_number_and_total(files):
    f = files["scan_clean.png"]
    r = ocr_image(Image.open(f.path))
    assert norm(f.gt["invoice_number"]) in norm(r.text)
    assert norm(f.gt["total"]) in norm(r.text)
    assert r.confidence > 80


def test_rotated_scan_is_deskewed(files):
    f = files["scan_rotated.png"]
    r = ocr_image(Image.open(f.path))
    assert norm(f.gt["invoice_number"]) in norm(r.text)


def test_deskew_finds_the_angle():
    import numpy as np, cv2
    img = np.full((800, 1200), 255, np.uint8)
    for y in range(100, 700, 40):
        cv2.putText(img, "INVOICE TOTAL 1234.56 PAID", (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    m = cv2.getRotationMatrix2D((600, 400), 4.0, 1.0)
    tilted = cv2.warpAffine(img, m, (1200, 800), borderValue=255)
    fixed = _deskew(tilted)
    def score(a):
        inv = (255 - a).astype(float)
        return np.var(inv.sum(axis=1))
    assert score(fixed) > score(tilted) * 1.5


def test_poor_scan_has_lower_confidence(files):
    good = ocr_image(Image.open(files["scan_clean.png"].path))
    bad = ocr_image(Image.open(files["scan_severe.jpg"].path))
    assert bad.confidence < good.confidence


def test_preprocess_upscales_small_images(files):
    small = Image.open(files["scan_severe.jpg"].path)
    assert preprocess(small).shape[1] >= 1700
