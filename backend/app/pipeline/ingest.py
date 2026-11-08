"""Stage 1: open the file, check it is readable, and split it into pages.

Every failure here is permanent (retrying will not fix a corrupted file),
so it raises IngestError with a code that is stored on the document and
shown to the user.
"""

from __future__ import annotations

import csv
import io
import warnings
from dataclasses import dataclass, field

import pandas as pd
import pymupdf
from PIL import Image

from .filetypes import sniff
from .text import Word, lines_from_words


class IngestError(Exception):
    """A permanent, user-facing failure. Messages never include library
    errors, which can contain server file paths."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PageData:
    number: int
    kind: str  # digital | scanned | sheet
    text: str | None = None
    sheet_name: str | None = None
    table: list[list] | None = None  # spreadsheets: rows of cell values


@dataclass
class IngestResult:
    format: str
    pages: list[PageData]
    warnings: list[str] = field(default_factory=list)


def ingest(path: str, declared_format: str, *, min_chars: int = 25, max_pixels: int = 120_000_000,
           max_rows: int = 50_000) -> IngestResult:
    with open(path, "rb") as fh:
        head = fh.read(8192)
    actual = sniff(head, path)
    if actual == "empty":
        raise IngestError("empty_file", "The file is empty")
    if actual is None:
        raise IngestError("corrupted", f"The file is not a readable {declared_format.upper()} file")
    if actual != declared_format and not (declared_format == "csv" and actual == "csv"):
        raise IngestError("corrupted", f"The file is named .{declared_format} but its content is {actual.upper()}")

    if actual == "pdf":
        return _pdf(path, min_chars)
    if actual in ("jpg", "png", "tiff"):
        return _image(path, actual, max_pixels)
    return _sheets(path, actual, max_rows)


# -- PDF ----------------------------------------------------------------------
def _pdf(path: str, min_chars: int) -> IngestResult:
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise IngestError("corrupted", "The PDF could not be opened; it is damaged or incomplete") from e
    if doc.needs_pass or doc.is_encrypted:
        raise IngestError("encrypted", "The PDF is password-protected")
    if doc.page_count == 0:
        raise IngestError("corrupted", "The PDF has no readable pages")
    warns = []
    if doc.is_repaired:
        warns.append("The PDF structure was damaged and has been repaired; check the result")
    pages = []
    for i in range(doc.page_count):
        try:
            page = doc[i]
            text = digital_text(page)
        except Exception as e:
            raise IngestError("corrupted", f"Page {i + 1} of the PDF is damaged and could not be read") from e
        if len(text.replace(" ", "").replace("\n", "")) >= min_chars:
            pages.append(PageData(i + 1, "digital", text))
        else:
            pages.append(PageData(i + 1, "scanned"))
    if doc.is_repaired and all(p.kind == "scanned" for p in pages) and not _has_images(doc):
        raise IngestError("corrupted", "The PDF is damaged and contains no readable content")
    doc.close()
    return IngestResult("pdf", pages, warns)


def _has_images(doc) -> bool:
    return any(doc[i].get_images() for i in range(doc.page_count))


def digital_text(page) -> str:
    words = [Word(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]
    return "\n".join(lines_from_words(words))


def render_pdf_page(path: str, page_number: int, dpi: int = 300) -> Image.Image:
    doc = pymupdf.open(path)
    try:
        pix = doc[page_number - 1].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        return Image.frombytes("L", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


# -- images -------------------------------------------------------------------
def _image(path: str, fmt: str, max_pixels: int) -> IngestResult:
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(path)
            n = getattr(im, "n_frames", 1)
            for f in range(n):
                im.seek(f)
                im.load()  # forces a full decode, so truncated files fail here
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise IngestError("corrupted", "Image is too large to process safely") from e
    except Exception as e:
        raise IngestError("corrupted", "The image could not be decoded; it is damaged or incomplete") from e
    return IngestResult(fmt, [PageData(i + 1, "scanned") for i in range(n)])


def render_image_page(path: str, page_number: int) -> Image.Image:
    im = Image.open(path)
    im.seek(page_number - 1)
    return im.convert("L")


def render_page(path: str, fmt: str, page_number: int) -> Image.Image:
    return render_pdf_page(path, page_number) if fmt == "pdf" else render_image_page(path, page_number)


# -- spreadsheets ---------------------------------------------------------------
def _sheets(path: str, fmt: str, max_rows: int) -> IngestResult:
    try:
        if fmt == "csv":
            sheets = {"CSV": _read_csv(path, max_rows)}
        else:
            engine = "openpyxl" if fmt == "xlsx" else "xlrd"
            raw = pd.read_excel(path, sheet_name=None, header=None, engine=engine, nrows=max_rows)
            sheets = {name: _rows(df) for name, df in raw.items()}
    except IngestError:
        raise
    except Exception as e:
        raise IngestError("corrupted", "The spreadsheet could not be read; it is damaged or not a real "
                                       f"{fmt.upper()} file") from e

    pages = []
    for i, (name, rows) in enumerate(sheets.items(), start=1):
        rows = [r for r in rows if any(c not in (None, "") for c in r)]
        text = "\n".join(" | ".join("" if c is None else str(c) for c in r) for r in rows)
        pages.append(PageData(i, "sheet", text, sheet_name=str(name), table=rows))
    if all(len(p.table) <= 1 for p in pages):
        raise IngestError("no_data", "The spreadsheet has no data rows")
    return IngestResult(fmt, pages)


def _rows(df: pd.DataFrame) -> list[list]:
    out = []
    for row in df.itertuples(index=False):
        cells = []
        for v in row:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                cells.append(None)
            elif isinstance(v, pd.Timestamp):
                cells.append(v.to_pydatetime())
            else:
                cells.append(v)
        out.append(cells)
    return out


def _read_csv(path: str, max_rows: int) -> list[list]:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise IngestError("corrupted", "CSV text encoding not recognised")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    rows = []
    for i, r in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
        if i >= max_rows:
            break
        rows.append([c.strip() if c.strip() else None for c in r])
    if delim == ";":
        rows.insert(0, ["__decimal_comma__"])  # marker read by the spreadsheet parser
    return rows
