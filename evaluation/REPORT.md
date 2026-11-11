# Evaluation report

This report gives the measured accuracy, speed, success rate and failure rate
of the document intelligence system, as required by Task 7 of the brief. Every
figure comes from a recorded run; the raw output of each run is in
`evaluation/runs/<label>/metrics.json` and `report.md`.

## 1. Summary

Official result: the held-out **test split**, processed once by the full
system with the real language model (`qwen3:8b`) on the target desktop,
10 November 2026.

| Metric | Result |
|---|---|
| Documents | 155 (185 invoices) |
| Document success rate (readable files processed) | **100%** |
| Unexpected failure rate (readable files that failed) | **0%** |
| Bad files rejected with the correct reason | **5 of 5** (3 corrupted, 1 encrypted, 1 with no data) |
| Invoices detected | 179 of 185 (96.8%) |
| Field accuracy, 8 header fields | **93.6%** |
| Invoices with every field and every line item correct | 76.2% |
| Line items: precision / recall | 94.6% / 90.8% |
| Invented values | 1.7% (1 of 58 fields that are not printed) |
| Silent errors (wrong but approved automatically) | **0 of 179** |
| Duplicate and cross-check groups found | 20 of 21 |
| 1,000-page PDF (760 invoices) | 760 of 760 split correctly, 99.1% field accuracy (section 3.8) |
| Throughput, whole run | 351 documents per hour, 400 pages per hour |
| Median time per digital PDF page | 153 ms |
| Median time per scanned page | 9.8 to 16.3 s, depending on format |

In short: digital PDFs and spreadsheets are read almost perfectly (99.6% to
100% field accuracy); scans and photos are where the errors are; and all 38
invoices read with errors were sent to a person for review rather than
approved (the six severe scans the scorer could not match are discussed in
section 3.3).

## 2. Dataset and method

### 2.1 Dataset

No labelled real invoices were available, and real invoices contain personal
and commercial data, so the dataset is synthetic: 219 documents holding 261
invoices, generated from known values so that every field has exact ground
truth. It covers all seven formats, four layouts, five regional conventions
(Bangladesh, United States, United Kingdom, Eurozone and US home care
billing), four scan quality levels, multi-invoice files, deliberate
arithmetic errors, missing fields, duplicates, PDF-to-PDF and PDF-to-Excel
pairs, and corrupted, empty and encrypted files. Full description:
[`dataset/README.md`](dataset/README.md).

Image quality levels: **clean** (a good scan), **mild**, **moderate**, and
**severe** (about 110 dpi with strong blur, noise, skew and faded ink).
"None" in the tables means a digital file that was never scanned.

### 2.2 Development and test split

The documents were split before any tuning into a **development split** (76
documents) and a **test split** (143 documents). All rule, prompt and
threshold changes were made by looking at development results only. The test
split was processed once, and that run is the official result.

The 21 duplicate and cross-check groups (42 documents) are always uploaded
whole, so that both halves of a pair are present. As a result:

- the test run contains the 143 test documents plus 12 documents from the
  development split (12 invoices, 6.5% of the total). Two of these, d177 and
  d178, are among the test run's error cases;
- the development runs contain the 76 development documents plus 30 from the
  test split.

### 2.3 Metrics

| Metric | Definition |
|---|---|
| Document success rate | Readable files that finished processing, divided by readable files |
| Unexpected failure rate | Readable files that ended as `failed` |
| Bad files rejected correctly | Corrupted, empty, encrypted or data-less files that failed with the expected error code |
| Field accuracy | Correct (invoice, field) pairs over all expected invoices and the 8 header fields. A field that is not printed counts as correct only if the system returned `null`. Invoices the system did not find count as wrong on every field |
| Fully correct | Every header field and every line item correct |
| Line-item precision / recall | Matched items over extracted items / over expected items |
| Invented values | Fields that are not printed but for which the system returned a value, over all fields that are not printed |
| Silent error | An invoice with any wrong field that the system approved automatically instead of sending to review |
| Flag precision / recall | Against the flags listed in each label. An "unexpected" flag on a misread invoice is the system correctly catching its own error; only unexpected flags on correctly read invoices are counted as false alarms |
| Processing time | From the first upload to the last document finishing, using server timestamps |

### 2.4 Environment

One desktop: AMD Ryzen 5 5500 (6 cores), 16 GB RAM, NVIDIA RTX 3050 with
8 GB, Windows with Docker Desktop (WSL 2). The language model `qwen3:8b`
(4-bit) and the embedding model `nomic-embed-text` ran in Ollama on the
Windows host, fully on the GPU. Five OCR processes, one model worker.

### 2.5 A correction to the scoring

The first scoring of the test run read the label files with the Windows
default text encoding instead of UTF-8, which garbled accented names in the
answer key (for example "Pölitz" became "PÃ¶litz"). Correct extractions were
therefore marked wrong on several Eurozone invoices and all spreadsheet
invoices with such names. The evaluation script was fixed and the same run
was scored again; the system, its output and the stored results were not
changed. The correction raised field accuracy from 93.2% to 93.6% and fully
correct invoices from 73.5% to 76.2%. Only the corrected figures are reported
here.

## 3. Results on the test split

### 3.1 By field

| Field | Accuracy | Correct | Correctly empty | Wrong | Missed | Invented |
|---|---|---|---|---|---|---|
| Invoice number | 94.6% | 173 | 2 | 3 | 6 | 1 |
| Invoice date | 95.7% | 171 | 6 | 1 | 7 | 0 |
| Supplier name | 84.9% | 157 | 0 | 22 | 6 | 0 |
| Customer name | 93.0% | 167 | 5 | 7 | 6 | 0 |
| Subtotal | 94.1% | 174 | 0 | 4 | 7 | 0 |
| Tax | 95.1% | 146 | 30 | 2 | 7 | 0 |
| Total | 95.7% | 177 | 0 | 1 | 7 | 0 |
| Currency | 96.2% | 164 | 14 | 1 | 6 | 0 |

Six of the misses in every row are the six invoices on severe scans, which
were not found at all (section 3.3). Apart from those, the system almost never
left a printed field empty. Supplier name is the weakest field; the reasons
are in section 5.

### 3.2 By format

| Format | Invoices | Field accuracy | Fully correct |
|---|---|---|---|
| Digital PDF | 61 | 99.6% | 96.7% |
| XLSX | 26 | 100% | 100% |
| XLS | 10 | 100% | 100% |
| CSV | 29 | 100% | 100% |
| Scanned PDF | 17 | 94.5% | 41.2% |
| JPG | 15 | 91.3% | 26.7% |
| PNG | 17 | 87.5% | 23.5% |
| TIFF | 9 | 79.7% | 22.2% |
| Mixed PDF (digital and scanned pages) | 1 | 87.5% | 0% |

The gap between field accuracy and fully correct on scans is mostly line
items: one misread digit in one line makes the invoice not fully correct.

### 3.3 By scan quality

| Quality | Invoices | Field accuracy | Fully correct |
|---|---|---|---|
| None (digital or spreadsheet) | 126 | 99.8% | 98.4% |
| Clean scan | 7 | 94.6% | 71.4% |
| Mild | 28 | 90.6% | 42.9% |
| Moderate | 18 | 85.4% | 0% |
| Severe | 6 | not measurable | 0% |

The six invoices on severe scans were not found. The documents completed and
the system produced an invoice for each, but so little was read correctly
that the scorer could not match any of them to its label (it needs at least
two fields to agree), so they count as wrong on every field. Their review
status was not recorded by the scorer. At this OCR quality every field's
confidence is capped below the review threshold, so they would be expected to
go to review, but this was not measured.

### 3.4 By region and by extraction method

| Region | Invoices | Field accuracy | Fully correct |
|---|---|---|---|
| Bangladesh | 50 | 96.7% | 72.0% |
| United States | 39 | 96.6% | 69.2% |
| United Kingdom | 36 | 99.0% | 88.9% |
| Eurozone | 25 | 90.0% | 64.0% |
| US home care | 35 | 99.3% | 85.7% |

| Method | Invoices | Field accuracy | Fully correct |
|---|---|---|---|
| Spreadsheet parser | 65 | 100% | 100% |
| Rules accepted (no model call) | 89 | 98.2% | 84.3% |
| Language model used | 25 | 83.0% | 4.0% |
| Not found | 6 | not measurable | 0% |

The model rows look poor because the model is only called for the hardest
invoices, the ones where the rules could not find every field or the
arithmetic did not agree. Section 4 compares the two approaches on equal
terms.

### 3.5 Validation and review

| Flag | Expected and raised | Missed | Unexpected | of which false alarms | Precision | Recall |
|---|---|---|---|---|---|---|
| `missing_field` | 27 | 1 | 2 | 0 | 93.1% | 96.4% |
| `total_mismatch` | 12 | 0 | 5 | 0 | 70.6% | 100% |
| `line_items_mismatch` | 6 | 0 | 11 | 0 | 35.3% | 100% |
| `line_amount_mismatch` | 5 | 0 | 14 | 1 | 26.3% | 100% |
| `tax_rate_mismatch` | 8 | 1 | 2 | 0 | 80.0% | 88.9% |
| `duplicate` | 40 | 2 | 0 | 0 | 100% | 95.2% |
| `cross_mismatch` | 24 | 0 | 6 | 3 | 80.0% | 100% |
| `low_confidence` | (not labelled) | | 53 | 17 | | |
| `ungrounded_value` | (not labelled) | | 20 | 7 | | |

Every deliberate arithmetic error in the test documents was caught (recall
100% for total, line-item and line-amount mismatches). The low precision of
the line checks is mostly the system catching its own OCR misreads: of 25
unexpected line flags, only 1 was on a correctly read invoice. False alarms
come mainly from `low_confidence` (17 invoices) and `ungrounded_value` (7):
correctly read invoices sent to review because a scan was faint or a value
could not be matched to the text exactly. This is the intended trade-off: a
reviewer checks some correct invoices so that no wrong invoice is approved.

**Silent errors: 0.** All 38 matched invoices with any error were marked
`needs_review`.

### 3.6 Duplicates and cross-verification

| | Result |
|---|---|
| Groups expected (6 duplicates, 10 PDF-to-Excel, 5 PDF-to-PDF) | 21 |
| Groups found | 20 |
| Groups with exactly the right differing fields listed | 17 |
| Unexpected groups | 1 |

Each document of a pair is read independently and then compared field by
field, so a reading error in either half shows up as a difference. This
explains the three groups whose list of differing fields was not exactly
right, and three of the six unexpected `cross_mismatch` flags; the other
three were false alarms on correctly read pairs.

While preparing the walkthrough, a timing fault was found when both halves
of a pair finish at the same moment: the second correctly flagged the first's
invoice for review, but the first document then saved its earlier status,
"completed". The invoice itself stayed in the review queue, so nothing was
approved, but the document's label was wrong. Document statuses are now
re-checked against the saved invoices after each document finishes (with a
test).

### 3.7 Speed

| Format | Median time per page |
|---|---|
| XLS | 94 ms |
| XLSX | 101 ms |
| CSV | 128 ms |
| Digital PDF | 153 ms |
| JPG | 9.8 s |
| PNG | 13.3 s |
| Scanned PDF | 15.2 s |
| TIFF | 16.3 s |
| Mixed PDF (one document) | 36.6 s |

| | Result |
|---|---|
| Whole test run (155 documents, including model loading) | 1,591.5 s |
| Throughput | 351 documents per hour, 400 pages per hour |
| Median time per document | 0.8 s |
| API median response: status / keyword search / hybrid search | 6.6 ms / 30.5 ms / 83.5 ms |

Scanned pages cost two orders of magnitude more than digital pages: OCR
takes several seconds per page, and those pages are also the ones that most
often need the model. Medians for single formats rest on few documents and
vary between runs (for example JPG was 15.9 s in the development run).

### 3.8 Large PDF (1,000 pages)

The brief describes PDFs of about 1,000 pages. One PDF of 1,000 pages holding
760 invoices was generated by `dataset/gen/stress.py` (seed 7): 898 digital
pages (679 invoices) and 102 scanned pages at mild quality (81 invoices), with
invoices of 3 to 45 line items. It was processed on 11 November 2026 on the
same desktop, with the real model.

| Metric | Result |
|---|---|
| Invoices split out of the 1,000 pages | **760 of 760**, none extra |
| Field accuracy, all / digital / scanned | **99.1%** / 99.8% / 93.2% |
| Invoices fully correct, digital / scanned | 99.0% / 40.7% |
| Line items: precision / recall | 99.7% / 99.3% |
| Invented values / silent errors | 0 / 0 |
| Ingest and OCR of all 1,000 pages | about 1 minute (102 pages through OCR) |
| Extraction of the 760 invoices | 3,780 s (63 minutes) |

**The model is the bottleneck at this size.** Splitting and OCR took about a
minute; extraction took 63 minutes because the single GPU answers one model
call at a time, about one every 20 to 25 seconds. 84 of the digital invoices
were sent to the model only because no currency is printed on them; the model
cannot supply a value that is not there, so those calls (roughly half an hour)
changed nothing. Skipping the model when the only gap is a field that is not
printed, and the arithmetic agrees, would roughly halve the time.

**The run exposed a reliability bug, now fixed.** With Redis as the queue, a
task that is not finished within the visibility timeout (one hour by default)
is handed out again. Extraction took just over an hour, so it ran a second
time (another 3,645 s), and the final stage of the first run collided with
the second run's results and failed. The second run completed normally, so
the document ended as needing review with all 760 invoices, but the run took
7,498 s in total and was scored as a failed document. As a result, the
evaluation's own totals for this run (480 pages per hour, a 0% success rate)
describe the collision, not normal operation. The timeout is now 12 hours,
and a document that succeeds on a retry no longer keeps the earlier error
code; both changes have tests. The run was not repeated for lack of time, so
the time of the final stage on its own was not measured.

An earlier attempt at the same file ran while the containers could not reach
the model. The system fell back to the rules for every invoice and sent
uncertain ones to review: 760 of 760 invoices, 99.1% field accuracy, no silent
errors, 1,000 pages in 101 seconds. This shows the fallback works at scale, but
it is not the normal configuration and is not used for the figures above.

## 4. Rules first versus model only

The system reads each invoice with deterministic rules first and calls the
language model only when a field is missing or the arithmetic does not agree.
To check whether that design is better than sending everything to the model,
the development documents were processed twice from an empty database:
once as normal, and once with every PDF and image sent to the model
(`DOCINTEL_EXTRACTION_MODE=llm_only`). Spreadsheets use the spreadsheet
parser in both runs.

| Metric (106 documents, 118 invoices) | Rules first | Model only |
|---|---|---|
| Field accuracy | **94.0%** | 92.3% |
| Invoices fully correct | **78.0%** | 72.0% |
| Silent errors | **0** | 3 (2.6%) |
| Invented values | 2 of 53 (3.8%) | **1 of 53 (1.9%)** |
| Line items: precision / recall | 96.2% / 94.6% | **96.6% / 95.1%** |
| Currency accuracy | **95.8%** | 86.4% |
| Customer name accuracy | **91.5%** | 89.0% |
| Supplier name accuracy | 85.6% | **86.4%** |
| `missing_field` raised wrongly | **2** | 17 |
| Digital PDF, median time per page | **152 ms** | 14,803 ms |
| Whole run | **772 s** | 1,805 s |
| Throughput | **494 documents per hour** | 211 documents per hour |

Findings:

1. **Rules first is more accurate and 2.3 times faster overall**, and about
   97 times faster on digital PDFs, which it read with 100% field accuracy.
2. **It is also safer.** The model-only run approved three wrong invoices:
   d104 (supplier and customer swapped, an address given as the customer),
   d080 (an OCR misreading of the supplier name) and d171 (a digital PDF with
   the subtotal left empty). In the rules-first run d080 and d104 went to
   review and d171 was read correctly. The two safeguards that send such
   invoices to review (a supplier name guessed from a scan is always
   reviewed, and so is any field on which the rules and the model disagree)
   both need the rules to run. On its own, the model's confidence in those
   wrong answers was high enough for automatic approval.
3. **The model is better at some things:** slightly better line items, one
   fewer invented value (a difference of one case), and more fully correct
   JPG invoices (36.4% against 27.3%).
4. **The model often leaves out the currency.** It returned no currency 16
   times on invoices that print a currency symbol ("$" or "€"); the rules map
   the symbol to its ISO code. This is also the cause of most of the 17 wrong
   `missing_field` flags.

**Caveat.** The rules and the prompts were both developed on these documents,
so the comparison is between two tuned configurations, not two untouched
ones. The test run in section 3 remains the official measure of accuracy.

## 5. Known issues

Every matched invoice below was sent to review; none was approved
automatically. Document IDs refer to the official test run.

| # | Issue | Documents | Cause |
|---|---|---|---|
| 1 | Wrong supplier name on scans | d065, d069, d072, d079, d090, d119, d172, d176 | On scans the supplier is often printed on a dark header band that OCR cannot read, so the first readable name (often the customer or a contact person) is taken |
| 2 | OCR misreadings carried into values | d054, d063, d085, d086, d087, d094, d095, d106, d107, d118, d218 | For example "Kennedy-Schmiat", "RushLLC", "2026/1 1/0693". The model cannot correct these, because the grounding check rejects values that do not appear in the OCR text |
| 3 | An address or a label taken as a name | d098, d101, d110, d112, d114, d115 | On some Eurozone, US and Bangladesh scans the model picked an address line (or "BILLED TO") as the customer and moved the real customer into the supplier field |
| 4 | Amounts read at the wrong scale | d063, d110, d112, d114 | Lost or misread separators on scans, especially Eurozone comma decimals (tax read as 25.96 instead of 25,964.29) |
| 5 | Ambiguous date | d032 | A US invoice with no currency shown; 07/05 was read day-first |
| 6 | Invented invoice number | d040 | The invoice has no number; the model took a number printed elsewhere on the page. The grounding check cannot catch a value that does appear in the text |
| 7 | Label text returned as a value | d066 | The invoice number was read as "INV. NO. :". A similar case in development (d057) took a table header as the supplier |
| 8 | Totals or tax not found | d074, d099 | The tax or the whole totals block was not picked up from the OCR text |
| 9 | Line items missed or misread on scans | d054 (16 of 41 matched), d218 (34 of 45); one to three items on d061, d105, d120, d172, d174, d177, d178 | Rows merged, split or misread by OCR |
| 10 | Severe scans unreadable | 6 invoices | Too little read correctly to match the invoice at all |

False alarms are listed in section 3.5. Issues 1, 6 and 7 were found after the
test run; fixing them now and re-running the test split would mean tuning to
the test set, so they are reported as found.

## 6. Limitations

- **Synthetic data.** Layouts are cleaner and more regular than real supplier
  invoices; the figures here should be read as an upper bound on real-world
  accuracy, especially for digital PDFs.
- **One machine, one run.** Timings come from a single consumer desktop and a
  single run of each configuration; run-to-run variation was not measured.
- **Severe scans** are not usable with Tesseract at this quality.
- **English only**, printed text only; handwriting is out of scope.
- **Dropped connections in the evaluation client.** During long runs the
  client often reported a dropped connection. The API log shows every request
  answered with status 200, so the drops happen between the client and the
  container, most likely when the client reuses a connection the server has
  already closed as idle. The client retries and no data was lost; the first
  time, before the retry existed, the run was scored again with `--resume`.
- **Progress during extraction.** The extraction stage saves its results
  only when it finishes, so for a long PDF the progress shown stays at the
  previous stage for the whole extraction.

What would improve results most, in order: reading the supplier from the
header band of scans (inverting dark regions before OCR), a vision-capable
model for scans, rejecting label text as a value, and a larger model where
hardware allows. For speed on large files: not calling the model for a field
that is simply not printed, and running more than one model worker where the
GPU allows.

## 7. Reproducing

From the project folder, with the system running (see the main README):

```powershell
$key = (Select-String '^DOCINTEL_API_KEY=' .env).Line.Split('=')[1]

# official test run, from an empty database
docker compose down -v
docker compose up -d
python evaluation\run_eval.py --api http://localhost:8000 --key $key --split test --label hybrid

# rules first versus model only, on the development split
powershell -ExecutionPolicy Bypass -File evaluation\run_comparison.ps1
```

`run_eval.py` uploads the documents through the API, waits for processing,
compares every result with its label, and writes `metrics.json` and
`report.md` to `evaluation/runs/<label>/`. If a run is interrupted,
`--resume` scores the documents already in the system without uploading
them again.
