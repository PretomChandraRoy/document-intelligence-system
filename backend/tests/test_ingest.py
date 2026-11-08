"""Stage 1: opening files, classifying pages, and clean failure on bad files."""
import pytest

from app.pipeline.ingest import IngestError, ingest


def test_digital_pdf_pages_have_text(files):
    r = ingest(files["long.pdf"].path, "pdf")
    assert r.format == "pdf" and len(r.pages) >= 2
    assert all(p.kind == "digital" for p in r.pages)
    assert files["long.pdf"].gt["invoice_number"] in r.pages[0].text


def test_scanned_pdf_pages_need_ocr(files):
    r = ingest(files["scanned.pdf"].path, "pdf")
    assert [p.kind for p in r.pages] == ["scanned"] * len(r.pages)


def test_mixed_pdf_is_classified_per_page(files):
    r = ingest(files["mixed.pdf"].path, "pdf")
    assert [p.kind for p in r.pages] == ["digital", "scanned"]


def test_multi_page_tiff(files):
    r = ingest(files["multi.tiff"].path, "tiff")
    assert len(r.pages) == 2 and all(p.kind == "scanned" for p in r.pages)


def test_workbook_sheets_become_pages(files):
    r = ingest(files["multisheet.xlsx"].path, "xlsx")
    names = [p.sheet_name for p in r.pages]
    assert names[:2] == ["Summary", "Items"]
    assert all(p.kind == "sheet" and p.table for p in r.pages)


@pytest.mark.parametrize("name,fmt,code", [
    ("encrypted.pdf", "pdf", "encrypted"),
    ("truncated.pdf", "pdf", "corrupted"),
    ("random.pdf", "pdf", "corrupted"),
    ("empty.png", "png", "empty_file"),
    ("renamed.xlsx", "xlsx", "corrupted"),      # text pretending to be Excel
    ("garbage.csv", "csv", "corrupted"),
    ("truncated.jpg", "jpg", "corrupted"),      # must not return half an image
    ("header_only.csv", "csv", "no_data"),
])
def test_bad_files_fail_with_a_reason(files, name, fmt, code):
    with pytest.raises(IngestError) as e:
        ingest(files[name].path, fmt)
    assert e.value.code == code
    assert e.value.message


def test_error_messages_do_not_leak_server_paths(files):
    for name, fmt in (("truncated.pdf", "pdf"), ("random.pdf", "pdf"), ("truncated.jpg", "jpg")):
        with pytest.raises(IngestError) as e:
            ingest(files[name].path, fmt)
        assert "/" not in e.value.message
