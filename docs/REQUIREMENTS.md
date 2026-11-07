# Requirements tracker

Every requirement in the assessment brief, where it is met, and its current
status. Status values: **Done** (built and verified), **Built** (implemented and
tested with the mock model; still to be verified with the real model on the
desktop), **Designed** (specified, not yet built), **Planned** (not started).

Last updated: 7 November 2026.

## Tasks

| # | Requirement | Where | Status |
|---|---|---|---|
| 1.1 | Accept multiple PDF, JPG, PNG, TIFF, XLSX, XLS and CSV files | `POST /documents`; ingest stage | **Done** |
| 1.2 | Extract text from digital PDFs | Ingest stage, PyMuPDF | **Done** |
| 1.3 | OCR for scanned documents and images | OCR stage, OpenCV and Tesseract | **Done** |
| 1.4 | Parse structured spreadsheet data | Ingest stage, pandas | **Done** |
| 1.5 | Multi-page PDFs, multiple sheets, poor image quality, corrupted files | Ingest and OCR stages; dataset covers each case | **Done** |
| 1.6 | PDFs mixing digital and scanned pages | Per-page classification; 3 mixed PDFs in the dataset | **Done** |
| 2.1 | Extract the nine invoice fields including line items | Extract stage | Built |
| 2.2 | Structured JSON output | `GET /invoices/{id}`; model JSON schema | Built |
| 2.3 | Missing or uncertain values handled without inventing | `null` for absent fields, grounding check, field confidence | Built |
| 3.1 | Missing fields, incorrect numeric values, duplicates | Validation rules `missing_field`, `implausible_value`, `duplicate` | **Done** |
| 3.2 | Subtotal, tax, line items and total consistency | `total_mismatch`, `line_items_mismatch`, `line_amount_mismatch`, `tax_rate_mismatch` | **Done** |
| 3.3 | Flag records for manual review | `review_status = needs_review` | **Done** |
| 3.4 | PDF-to-PDF and PDF-to-Excel cross-verification (scenario) | Invoice groups and field comparison; `/groups`, `/cross-verify` | **Done** |
| 4.1 | REST APIs: upload, status, results, search, corrections, reprocessing | `docs/API.md` | **Done** |
| 4.2 | Background processing for OCR and AI | Celery with Redis, four queues | **Done** |
| 5.1 | Store metadata, text, results, validation errors, history | `docs/DATABASE.md` | **Done** |
| 5.2 | Keyword filtering and semantic search | Full-text index, pgvector, hybrid ranking | **Done** |
| 6.1 | Next.js interface: upload, progress, inspect, errors, correct, search | Frontend | Planned |
| 7.1 | Automated tests: processing, OCR, spreadsheets, extraction, validation, API, failures | `backend/tests/`, 133 tests | **Done** |
| 7.2 | Labelled evaluation dataset | `evaluation/dataset/`, 219 documents | **Done** |
| 7.3 | Report measured accuracy, processing time, success rate, failure rate | `evaluation/REPORT.md` | Planned |

## Deliverables

| # | Deliverable | Where | Status |
|---|---|---|---|
| 1 | Git repository with source code | GitHub, public | Planned |
| 2 | README and setup instructions | `README.md` | Planned |
| 3 | Architecture diagram and database schema | `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/diagrams/` | **Done** |
| 4 | Working backend API and frontend | `backend/` built; `frontend/` planned | Backend built |
| 5 | PDF, image, Excel and CSV pipelines | `backend/app/pipeline/` | **Done** |
| 6 | Automated tests and test results | `backend/tests/`, `evaluation/test-results/` (JUnit and coverage) | Preliminary run done; final run on desktop |
| 7 | Evaluation report with measured metrics | `evaluation/REPORT.md` | Planned |
| 8 | Recorded walkthrough | Video link in `README.md` | Planned |
| 9a | AI prompts used by the system | `backend/app/prompts/` | **Done** |
| 9b | Disclosure of AI-assisted development | `docs/AI_DISCLOSURE.md` | Planned |

## Quality requirements

| Requirement | How it is shown | Status |
|---|---|---|
| Performance and speed | Measured time per page by format; documents per hour; API response times | Planned |
| Scalability | Separate queues, stateless API; 1,000-page PDF run | Designed |
| Reliability | Retries, idempotent tasks, reprocessing; failure-scenario tests | **Done** (tested) |
| Security | API key, file-signature checks, limits, local model; listed in `ARCHITECTURE.md` section 8 | Built |
