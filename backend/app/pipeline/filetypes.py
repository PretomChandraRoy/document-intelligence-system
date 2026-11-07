"""Identify a file's real type from its first bytes ("magic numbers").

File extensions are chosen by whoever sends the file, so they cannot be
trusted. Every format we accept starts with a recognisable signature,
except CSV, which is plain text and is recognised by being decodable text
with a delimiter.
"""

from __future__ import annotations

import io
import zipfile

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "tif", "tiff", "xlsx", "xls", "csv"}
CANONICAL = {"jpeg": "jpg", "tif": "tiff"}

OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy Office container (XLS)


def extension_of(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return CANONICAL.get(ext, ext)


def sniff(head: bytes, full_path: str | None = None) -> str | None:
    """Return 'pdf', 'jpg', 'png', 'tiff', 'xlsx', 'xls', 'csv', 'empty' or None."""
    if not head:
        return "empty"
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if head.startswith(OLE2):
        return "xls"
    if head.startswith(b"PK\x03\x04"):
        # XLSX is a zip archive; so are DOCX and many others, so look inside
        try:
            src = full_path if full_path else io.BytesIO(head)
            with zipfile.ZipFile(src) as z:
                names = set(z.namelist())
            if "xl/workbook.xml" in names:
                return "xlsx"
        except zipfile.BadZipFile:
            return None
        return None
    if _looks_like_text_table(head):
        return "csv"
    return None


def _looks_like_text_table(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = head.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return False
    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
    if printable / max(len(text), 1) < 0.97:
        return False
    lines = text.splitlines()[:10]
    return any(d in ln for ln in lines for d in (",", ";", "\t", "|"))
