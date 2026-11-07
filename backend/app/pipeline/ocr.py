"""OCR for scanned pages and images: clean the image, then run Tesseract.

Tesseract is trained on clean, upright, high-resolution black-on-white text.
Each step below moves a real scan closer to that:

1. upscale    low-resolution scans to about 300 dpi, the size Tesseract expects
2. flatten    uneven lighting by dividing by an estimate of the background
3. deskew     by measuring the angle of the text lines and rotating back
4. denoise    with a small median filter, which removes specks but keeps edges
5. binarise   with Otsu's method, which picks the black/white threshold
              from the image's own histogram
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract
from PIL import Image

from .text import Word, lines_from_words

TARGET_WIDTH = 2480  # A4 width in pixels at 300 dpi


@dataclass
class OcrResult:
    text: str
    confidence: float  # mean word confidence, 0 to 100
    words: list[Word]
    ms: int


def preprocess(img: Image.Image, target_width: int = 2000, binarise: bool = False) -> np.ndarray:
    a = np.array(img.convert("L"))

    # denoise first, at the original size: noise grows when the image is enlarged
    a = cv2.fastNlMeansDenoising(a, None, h=12, templateWindowSize=7, searchWindowSize=21) \
        if a.shape[1] <= 1400 else cv2.medianBlur(a, 3)

    # deskew at the original size as well, where it is cheaper
    a = _deskew(a)

    # upscale small images so letters are large enough for Tesseract
    h, w = a.shape
    if w < target_width * 0.85:
        scale = target_width / w
        a = cv2.resize(a, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    # flatten uneven lighting: divide by a heavily blurred copy (the paper colour)
    small = cv2.resize(a, None, fx=0.125, fy=0.125)
    bg = cv2.resize(cv2.medianBlur(small, 21), (a.shape[1], a.shape[0]), interpolation=cv2.INTER_LINEAR)
    a = cv2.divide(a, bg, scale=255)

    if binarise:
        _, a = cv2.threshold(a, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return a


def _deskew(a: np.ndarray, max_angle: float = 6.0, step: float = 0.25) -> np.ndarray:
    """Find the rotation that makes text lines most horizontal.

    For each candidate angle the dark pixels are summed row by row. When the
    lines are level, rows alternate sharply between ink and blank paper, so
    the variance of those row sums is highest at the correct angle.
    """
    small = cv2.resize(a, None, fx=600 / a.shape[1], fy=600 / a.shape[1]) if a.shape[1] > 600 else a
    inv = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1].astype(np.float32)
    h, w = inv.shape
    best, best_score = 0.0, -1.0
    for ang in np.arange(-max_angle, max_angle + step, step):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        rot = cv2.warpAffine(inv, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        score = float(np.var(rot.sum(axis=1)))
        if score > best_score:
            best, best_score = float(ang), score
    if abs(best) < 0.2:
        return a
    H, W = a.shape
    m = cv2.getRotationMatrix2D((W / 2, H / 2), best, 1.0)
    return cv2.warpAffine(a, m, (W, H), flags=cv2.INTER_CUBIC, borderValue=255)


def ocr_image(img: Image.Image, lang: str = "eng", psm: int = 4, clean: bool = True) -> OcrResult:
    t0 = time.perf_counter()
    arr = preprocess(img) if clean else np.array(img.convert("L"))
    data = pytesseract.image_to_data(arr, lang=lang, config=f"--oem 1 --psm {psm}",
                                     output_type=pytesseract.Output.DICT)
    words, confs = [], []
    for i, txt in enumerate(data["text"]):
        txt = txt.strip()
        conf = float(data["conf"][i])
        if not txt or conf < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append(Word(x, y, x + w, y + h, txt, conf))
        confs.append(conf)
    text = "\n".join(lines_from_words(words))
    return OcrResult(text, float(np.mean(confs)) if confs else 0.0, words,
                     int((time.perf_counter() - t0) * 1000))
