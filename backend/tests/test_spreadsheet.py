"""Spreadsheet parsing: form, multi-sheet and ledger layouts, XLS and CSV."""
import pytest

from app.pipeline.ingest import ingest
from app.pipeline.spreadsheet import parse_workbook
from tests.helpers import mismatches


@pytest.mark.parametrize("name,fmt", [
    ("form.xlsx", "xlsx"), ("multisheet.xlsx", "xlsx"), ("ledger.xlsx", "xlsx"),
    ("form.xls", "xls"), ("ledger.csv", "csv"), ("eu.csv", "csv"),
])
def test_every_field_matches_ground_truth(files, name, fmt):
    f = files[name]
    got = parse_workbook(ingest(f.path, fmt).pages)
    assert len(got) == len(f.truth)
    for inv, truth in zip(got, f.truth):
        assert inv.method == "spreadsheet"
        assert mismatches(inv.as_dict(), truth) == []


def test_ledger_groups_rows_into_invoices(files):
    got = parse_workbook(ingest(files["ledger.xlsx"].path, "xlsx").pages)
    assert [len(i.line_items) for i in got] == [2, 3, 1]


def test_native_cells_get_high_confidence(files):
    inv = parse_workbook(ingest(files["form.xlsx"].path, "xlsx").pages)[0]
    assert inv.confidence["total"] >= 0.95
    assert "row" in inv.evidence["total"]
