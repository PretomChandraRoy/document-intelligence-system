"""Real file types are detected from content, not from the extension."""
import pytest

from app.pipeline.filetypes import extension_of, sniff


@pytest.mark.parametrize("name,expected", [
    ("classic.pdf", "pdf"), ("scan_clean.png", "png"), ("scan_mild.jpg", "jpg"), ("multi.tiff", "tiff"),
    ("form.xlsx", "xlsx"), ("form.xls", "xls"), ("ledger.csv", "csv"), ("eu.csv", "csv"),
    ("empty.png", "empty"), ("random.pdf", None), ("garbage.csv", None), ("notes.docx", None),
    ("renamed.xlsx", "csv"),
])
def test_sniff(files, name, expected):
    path = files[name].path
    assert sniff(open(path, "rb").read(8192), path) == expected


def test_extension_normalised():
    assert extension_of("SCAN.JPEG") == "jpg"
    assert extension_of("a.b.TIF") == "tiff"
    assert extension_of("noext") == ""
