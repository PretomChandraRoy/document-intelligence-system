"""Turn clean PDF pages into realistic scans and phone photos.

Severity levels map to what a back office actually receives:
  clean    - a good flatbed scan
  mild     - slight skew, light noise
  moderate - visible skew, blur, uneven lighting, JPEG artefacts
  severe   - low resolution, strong blur and noise, faded contrast
"""

from __future__ import annotations

import io
import random

import cv2
import numpy as np
import pymupdf
from PIL import Image

SEVERITY = {
    "clean":    dict(dpi=200, angle=0.0, blur=0, noise=0, contrast=1.0, shadow=0.0, jpeg=95),
    "mild":     dict(dpi=170, angle=1.0, blur=0, noise=6, contrast=0.95, shadow=0.05, jpeg=85),
    "moderate": dict(dpi=150, angle=2.5, blur=1, noise=12, contrast=0.85, shadow=0.18, jpeg=60),
    "severe":   dict(dpi=110, angle=4.0, blur=2, noise=20, contrast=0.65, shadow=0.30, jpeg=35),
}


def pdf_to_images(pdf_path: str, dpi: int) -> list[Image.Image]:
    doc = pymupdf.open(pdf_path)
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        out.append(Image.frombytes("L", (pix.width, pix.height), pix.samples))
    doc.close()
    return out


def degrade(img: Image.Image, level: str, rng: random.Random) -> Image.Image:
    p = SEVERITY[level]
    a = np.array(img.convert("L"), dtype=np.float32)

    if p["angle"]:
        angle = rng.uniform(-p["angle"], p["angle"])
        h, w = a.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        a = cv2.warpAffine(a, m, (w, h), borderValue=255)

    if p["shadow"]:
        # uneven lighting: a linear gradient darkening one side of the page
        h, w = a.shape
        ramp = np.linspace(0, 1, w if rng.random() < 0.5 else h, dtype=np.float32)
        if rng.random() < 0.5:
            ramp = ramp[::-1]
        grad = ramp[None, :] if ramp.shape[0] == w else ramp[:, None]
        a = a * (1 - p["shadow"] * grad)

    if p["contrast"] != 1.0:
        a = 255 - (255 - a) * p["contrast"]  # faded ink

    if p["blur"]:
        k = 2 * p["blur"] + 1
        a = cv2.GaussianBlur(a, (k, k), 0)

    if p["noise"]:
        nrng = np.random.default_rng(rng.randint(0, 2**31))
        a = a + nrng.normal(0, p["noise"], a.shape)
        # a few dust specks
        n = int(a.size * 0.0004)
        ys = nrng.integers(0, a.shape[0], n)
        xs = nrng.integers(0, a.shape[1], n)
        a[ys, xs] = nrng.integers(0, 80, n)

    a = np.clip(a, 0, 255).astype(np.uint8)
    out = Image.fromarray(a, "L")

    # round-trip through JPEG to add compression artefacts
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=p["jpeg"])
    buf.seek(0)
    return Image.open(buf).convert("L")


def scan_pdf(src_pdf: str, level: str, rng: random.Random) -> list[Image.Image]:
    return [degrade(im, level, rng) for im in pdf_to_images(src_pdf, SEVERITY[level]["dpi"])]


def save_images_as_pdf(images: list[Image.Image], path: str, dpi: int) -> None:
    """A scanned PDF: image-only pages, no text layer."""
    rgb = [im.convert("RGB") for im in images]
    rgb[0].save(path, "PDF", save_all=True, append_images=rgb[1:], resolution=dpi)
