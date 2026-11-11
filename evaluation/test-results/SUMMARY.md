# Test results

| | |
|---|---|
| Date | 11 November 2026, on the final code |
| Result | **143 passed, 0 failed** |
| Line coverage | 92% of `backend/app` |
| Duration | 23 s |
| Environment | Linux (the development workspace): Python 3.13, PostgreSQL 16 with pgvector 0.6, Redis 7, Tesseract 5.3.4. The suite needs PostgreSQL and Tesseract outside Docker, so it was not run on the Windows desktop; the system's behaviour on that desktop, with the real model, is measured by the [evaluation report](../REPORT.md) |
| Language model | Mock client (deterministic); the real model is exercised by the evaluation, not the unit tests |

Files: `junit.xml` (machine-readable, one entry per test) and
`coverage-html/index.html` (line-by-line coverage).

## What the suite covers

| Brief requirement (Task 7) | Test file | Tests |
|---|---|---|
| Document processing | `test_ingest.py`, `test_filetypes.py`, `test_matching_segment.py` | Page classification (digital, scanned, mixed), multi-page TIFF, workbook sheets, file-type detection from content, splitting multi-invoice PDFs |
| OCR | `test_ocr.py` | Reading a clean scan, deskewing a rotated scan, skew-angle estimation, lower confidence on poor scans, upscaling |
| Spreadsheet parsing | `test_spreadsheet.py` | Form, multi-sheet and ledger layouts in XLSX, XLS and CSV (including semicolon and decimal-comma CSV), every field against ground truth |
| AI extraction | `test_extract.py`, `test_rules.py` | Rules accepted without a model call, model called when rules are inconsistent, invented values discarded, nulls preserved, disagreements flagged, long invoices sent in parts, model outage fallback, Ollama request format and timeouts |
| Validation | `test_validate.py` | Every rule: missing fields, total, line-item and line-amount mismatches, tax rate, implausible values, low confidence, model warnings |
| API endpoints | `test_api.py` | Authentication, upload of each format, multi-file upload with rejection, results JSON, history, file and page image, corrections with audit trail, review rules, duplicates, PDF-Excel cross-verification, manual cross-verify, keyword, semantic and hybrid search, export, reprocessing, statistics |
| Failure scenarios | `test_ingest.py`, `test_api.py` | Encrypted, truncated, random-byte, empty, renamed, half-downloaded and header-only files; model outage; unexpected internal error |
| Reliability fixes found by the evaluation | `test_api.py` | A long stage is not handed out twice by the queue; a stage that succeeds on retry clears the earlier error; document statuses are corrected when grouped documents finish at the same moment |

In addition, the API and a real (non-eager) Celery worker were run together
against local PostgreSQL and Redis, and documents were uploaded over HTTP,
including an 8-page scanned bundle processed through parallel OCR batches.
All documents reached their expected status.
