# Learning notes

One entry per component: the concept, the decisions taken, and questions an
interviewer is likely to ask, with answers. Read an entry before working on
that part of the system.

---

## 1. The evaluation dataset

**What it is.** 219 generated documents (261 invoices) with a JSON label for
each, stating exactly what a perfect system would extract and which
validation flags it should raise. Code: `evaluation/dataset/gen/`.

### Concepts

**Ground truth.** The correct answer for each input, fixed before the system
runs. Without it, "accuracy" is a guess. Because we generate the invoice as
data first and only then draw it, the ground truth is exact by construction.

**Printed value versus correct value.** If an invoice prints a total of 1,200
when the items add up to 1,150, the extractor must return 1,200: its job is to
read faithfully. Spotting that 1,200 is wrong is the validator's job. Keeping
the two apart lets us measure each stage on its own, and it matches the brief's
"without inventing values".

**`null` is an answer.** When a field is not on the document, the correct
output is `null`. A model that fills in a plausible date is producing a
hallucination, and that is worse than a blank because nobody checks it.
The dataset contains documents with missing fields specifically to measure this.

**Dev/test split.** 30% of documents are marked `dev`. We tune prompts, OCR
settings and thresholds by looking only at dev results, then report numbers on
`test`. If we tuned on the same documents we report on, the numbers would be
inflated, because we would have fitted the system to those exact files.

**Decimal, not float.** `0.1 + 0.2` in floating point is `0.30000000000000004`.
Money is stored with Python's `Decimal` and serialised as strings so that a
one-cent discrepancy is a real discrepancy and not a rounding artefact.

**Reproducibility.** Every random choice comes from a seeded generator, so the
same seed always gives the same 219 files. Anyone can regenerate and check.

### Design decisions

| Decision | Reason |
|---|---|
| Five locales, including Bangladesh and US home care | Matches the employer's back-office billing work and creates realistic format variety (Indian digit grouping, comma decimals, day-first and month-first dates) |
| Four layout families with different field labels ("Total", "Amount Due", "TOTAL PAYABLE", "Balance Due") | An extractor that only works on one template is useless |
| Four scan quality levels | Lets us report accuracy per quality level, which is more honest and more useful than one average |
| Corrupted files in the set | The brief requires clean failure handling, so failures are measured too |
| The 1,000-page file is generated, not committed | It is about 100 MB and fully reproducible |

### An early finding

Running plain Tesseract on the scans, with no image preprocessing: on
14 moderate JPG/PNG scans it read the invoice number correctly in 10; on the 6
severe scans it read it in none. This was a quick check, not the evaluation. This tells us image preprocessing
(upscaling, deskewing, denoising, binarisation) is not optional, and the
evaluation will show accuracy per quality level.

### Likely interview questions

**Q: Why should we trust results on synthetic data?**
A: The ground truth is exact, so the measurement itself is reliable. What is
uncertain is how well the documents represent real ones. I report the numbers
as an upper bound, show them broken down by format and quality level, and list
what the generator does not model (perspective distortion, handwriting, folds,
non-English text). The next step would be labelling a sample of real invoices.

**Q: How did you avoid overfitting to your own test set?**
A: A fixed dev/test split. Tuning decisions were made on dev documents only.

**Q: What is the difference between a duplicate and a cross-verification
mismatch?**
A: Both are the same invoice appearing in more than one document. A duplicate
agrees on every field, which usually means it was submitted twice. A
cross-verification mismatch disagrees on some fields, for example the PDF says
quantity 5 and the accounting spreadsheet says 6, which means one record is
wrong and a person must check it.

**Q: Why is the tax `null` and not `0` when there is no tax line?**
A: Because the document does not say the tax is zero; it says nothing. Those
are different facts, and a downstream accounting system may treat them
differently.

---

## 2. Architecture

Read with `docs/ARCHITECTURE.md`.

### Concepts

**Why a background queue.** OCR on a 40-page scan takes tens of seconds and
the model takes seconds per invoice. If the upload request waited for that,
the browser would time out and one large file would block every other user.
So the API only saves the file, writes a database row and puts a message on
a queue, then answers `202 Accepted` at once. Separate worker processes take
messages off the queue and do the slow work. The frontend asks for progress
every two seconds (polling).

**Broker.** Redis holds the queue of pending tasks. Celery is the library
that puts tasks on it (in the API) and runs them (in the workers).

**Why four queues.** The stages use different resources: OCR uses CPU cores,
the model uses the single GPU. With one queue, ten OCR jobs could sit in
front of a quick extraction job. With separate queues, OCR can run six in
parallel (one per core) while extraction runs one at a time, and each can be
scaled on its own.

**Idempotency.** A task is idempotent if running it twice leaves the same
result as running it once. Tasks can run twice (a worker crashes after
finishing but before reporting), so every stage deletes its previous output
for that document before writing new output.

**Retries with backoff.** If Ollama times out, the task waits 2 s, then 4 s,
then 8 s before trying again, instead of hammering a struggling service.
Errors that will never succeed (an encrypted PDF) are not retried.

**Rules first, model second.** Rules are fast, free and predictable, but
brittle on unfamiliar layouts. A language model handles any layout but is
slow and can invent things. We use rules where their result can be checked
(the arithmetic agrees) and the model for the rest.

**Grounding.** After the model answers, we check that each value actually
appears in the document text. A value that cannot be found is thrown away
and the field set to null. This turns "the model might hallucinate" into a
measurable, controlled risk.

### Likely interview questions

**Q: What happens when a worker crashes halfway through a 1,000-page PDF?**
A: Tasks are acknowledged only after they finish (`acks_late`), so the
unfinished task goes back on the queue and another worker picks it up. OCR
runs in batches of 20 pages, so only the current batch is redone, and
because tasks are idempotent the redo does not create duplicate rows.

**Q: Why not call the model for every invoice?**
A: Speed and reliability. On one consumer GPU the model takes seconds per
invoice; across a 1,000-page file that is a long time. Rules handle the
easy, verifiable cases in milliseconds, and the evaluation reports how many
invoices each tier handled so the trade-off is visible.

**Q: How would you scale this to many machines?**
A: The API holds no state, so more API containers can sit behind a load
balancer. Workers already scale per queue. The two changes are moving the
file store to S3-compatible object storage, so every machine can read the
files, and running the model on a dedicated GPU server or a hosted API.

**Q: Why polling and not WebSockets?**
A: Progress changes every second or two, polling every two seconds is cheap,
and it survives page reloads and proxies without extra infrastructure.
Server-sent events would be the next step if the number of users grew.

---

## 3. Database

Read with `docs/DATABASE.md`.

### Concepts

**Relational design.** Each kind of thing has its own table, linked by
foreign keys: a document has pages and invoices, an invoice has line items
and issues. This avoids storing the same fact twice, and lets the database
enforce rules such as "a line item must belong to an existing invoice".

**`numeric`, not `float`.** `numeric(14,2)` stores exact decimals, the same
reason the dataset uses Python's `Decimal`.

**UUID keys.** Unguessable in URLs (nobody can try `/invoices/1`,
`/invoices/2`), and can be created before the row is inserted.

**Indexes** make lookups fast at the cost of slower writes and some disk
space. Three kinds are used:
- *B-tree*, the default, for equality and ranges: dates, totals, status.
- *GIN* for "contains" searches: full-text (`tsvector`) and fuzzy name
  matching (`pg_trgm`, which compares names by shared three-letter chunks,
  so "Padma Office Solutions Ltd" matches "Padma Office Solution").
- *HNSW* for vector similarity: an approximate nearest-neighbour index over
  embeddings, which finds the closest vectors without comparing against
  every row.

**Full-text search.** `tsvector` stores a document as a list of normalised
words; a `tsquery` is matched against it and ranked with `ts_rank`. We use
the `simple` configuration (no English stemming) because invoices are full
of names and codes that stemming would damage.

**Embeddings and semantic search.** An embedding model turns text into a
list of 768 numbers so that texts with similar meaning have nearby vectors.
"Printer ink" and "toner cartridge" share no words but have similar
embeddings. Cosine distance (`<=>` in pgvector) measures how close two are.

**Hybrid search with reciprocal rank fusion.** Run keyword search and
semantic search separately, then score each result as
`1/(60 + rank_keyword) + 1/(60 + rank_semantic)`. Results that rank well in
both rise to the top. It needs no tuning because it uses ranks, not the two
incompatible score scales.

**Audit trail.** Corrections are never written over silently: every change
is stored with old value, new value, who and when. In finance this is
usually a compliance requirement.

### Likely interview questions

**Q: Why PostgreSQL and not MongoDB?**
A: The data is relational (invoices have line items, issues and
corrections), money needs an exact decimal type, and pgvector gives vector
search in the same database. JSONB columns still store the flexible parts,
such as the raw model output.

**Q: Why not a dedicated vector database?**
A: At this scale pgvector is fast enough, and keeping vectors next to the
invoice rows means one query can combine "semantically similar" with "BDT,
after June, unreviewed". A separate vector store would need keeping in sync.

**Q: How is a duplicate detected?**
A: Two levels. An exact re-upload has the same SHA-256 hash and is caught at
upload. The same invoice in a different file (a PDF and a photo of it, or a
PDF and its spreadsheet record) shares a normalised supplier-plus-number
key, with a fuzzy fallback on name similarity, date and total when the
number is missing.

---

## 4. API

Read with `docs/API.md`.

### Concepts

**REST.** Resources (documents, invoices, groups) have URLs, and HTTP verbs
say what to do: `GET` reads, `POST` creates or triggers an action, `PATCH`
changes part of a resource. Status codes say how it went.

**`202 Accepted`** means "received, will be processed later", which is
exactly what an upload into a queue is. `201 Created` would wrongly suggest
the result already exists.

**`PATCH` for corrections** because the reviewer changes a few fields, not
the whole invoice. Sending only changed fields also makes the audit trail
precise.

**Partial success on upload.** Each file is checked separately and the
response lists accepted and rejected files. One `.docx` in a batch of twenty
should not block the other nineteen.

**Money as strings in JSON.** JSON numbers are read as floating point by
JavaScript, which would bring back the rounding problem. Strings carry exact
values; the frontend formats them for display.

**Keeping the key out of the browser.** Anything sent to the browser can be
read by the user. The browser talks to the Next.js server, which adds the
API key and forwards the request to FastAPI.

**OpenAPI.** FastAPI generates a machine-readable description of every
endpoint from the Python type hints. It powers the `/docs` page and is used
to generate the frontend's TypeScript types, so frontend and backend cannot
drift apart silently.

### Likely interview questions

**Q: How does a reviewer fix a wrong value, and what happens next?**
A: `PATCH /invoices/{id}` with the changed fields. The change is recorded in
`corrections`, validation runs again on the corrected invoice, resolved
issues are marked resolved, and the invoice becomes `reviewed` if nothing
blocking remains.

**Q: How do you reprocess failed jobs?**
A: `POST /documents/{id}/reprocess`, optionally from a given stage so OCR
does not have to be repeated after, say, a model timeout; or
`POST /documents/reprocess-failed` for all of them. Each attempt is a new
row in `processing_runs`, so the history shows every try.

---

## 5. Reading documents: ingest and OCR

Code: `backend/app/pipeline/filetypes.py`, `ingest.py`, `text.py`, `ocr.py`.

### Concepts

**Magic numbers.** Every binary format starts with a fixed signature: PDF
with `%PDF-`, PNG with `\x89PNG`, JPEG with `FF D8 FF`. We trust these, not
the extension. An XLSX file is a zip archive, so we also look inside it for
`xl/workbook.xml`, which tells it apart from a Word file. CSV has no
signature, so it is recognised as decodable text containing a delimiter.

**Digital or scanned, page by page.** A PDF page with a text layer is read
directly in milliseconds. A page with fewer than 25 characters of text is
treated as a scan and sent to OCR. Deciding per page handles PDFs that mix
both.

**Rebuilding lines from positioned words.** PDF text and OCR both return
words with coordinates. We group words with the same vertical position into
lines and keep wide horizontal gaps as four spaces. That preserves columns,
so "Unit Price" stays above its numbers and "Invoice No:" stays next to its
value.

**Image clean-up before OCR**, in this order:
1. *Denoise* at the original size (a non-local-means filter), because
   enlarging an image enlarges its noise too.
2. *Deskew*: try angles from -6 to +6 degrees and keep the one where the
   row-by-row ink totals vary most. Level text lines make sharp alternation
   between ink rows and blank rows.
3. *Upscale* small images to about 2,000 pixels wide, so letters are tall
   enough for Tesseract.
4. *Flatten lighting*: divide the image by a heavily blurred copy of itself,
   which approximates the paper colour, removing shadows.

**Page segmentation mode.** Tesseract's `--psm 4` assumes a single column of
text of varying sizes, which suits invoices better than the default.

### What we measured (dev documents only)

Share of scans where the invoice number was read exactly:

| Setting | Clean | Mild | Moderate | Severe | Time per page |
|---|---|---|---|---|---|
| Plain Tesseract | 8/8 | 9/9 | 6/10 | 0/5 | 0.7 s |
| First clean-up attempt (hard black/white) | 8/8 | 8/9 | 8/10 | 0/5 | 8.5 s |
| Final clean-up, psm 4 | 8/8 | 9/9 | **10/10** | 0/5 | 1.8 s |

The first attempt was slower and no better, because forcing every pixel to
black or white destroyed thin strokes on noisy images. The final version
leaves the image in greyscale. **Severe scans stay unreadable** with
Tesseract. The system's job there is to know it cannot read them: the low
OCR confidence caps every field's confidence, so those invoices always go to
manual review instead of being trusted.

### Likely interview questions

**Q: How do you handle a corrupted file?**
A: Ingest opens it fully before anything else; a truncated JPEG is decoded
completely, so it fails there and not halfway through extraction. The
document gets a specific error code (`corrupted`, `encrypted`,
`empty_file`, `no_data`) and is not retried, because retrying cannot fix it.

**Q: Why not use a deep-learning OCR model?**
A: PaddleOCR or a vision-language model would read severe scans better,
but they compete with the extraction model for the single 8 GB GPU. It is
the natural next step, and the interface makes it a swap of one function.

---

## 6. Extraction: rules, model, grounding

Code: `backend/app/pipeline/rules.py`, `llm.py`, `extract.py`, `spreadsheet.py`.
Prompts: `backend/app/prompts/`.

### Concepts

**Labels, not templates.** The rules look for general accounting labels
("Invoice No", "Bill To", "Amount Due", "Balance Due") from a shared list in
`labels.py`, wherever they sit on the page, rather than at fixed positions.

**Line items by arithmetic.** A line ending in three numbers where quantity
times price equals the amount is almost certainly an item row read
correctly.

**Self-checking.** If every required field is found and the sums agree, the
rules result is accepted without the model. If the sums do not agree, the
model is asked as a second reader. When both read the same numbers, the
document itself is wrong and validation will say so.

**Structured output.** Ollama is given a JSON schema, and the model's
decoding is constrained to it, so the reply always parses.

**Copy, do not interpret.** The prompt asks for values exactly as printed.
Converting "1,23,456.00" or "07/11/2026" is done by our code, which is
predictable, not by the model.

**Grounding.** Each value the model returns must be findable in the
document text (after removing spaces and punctuation). If not, it is
dropped and a warning is recorded. This is tested directly in
`test_extract.py::test_invented_value_is_discarded`.

**Merging two readers.** Agreement raises confidence; a value only one side
found is kept; a disagreement on money is settled by whichever reading
makes the sums agree; any other disagreement is shown to a person.

**Long invoices** are sent in parts: header and totals from the first and
last pages, then line items page by page, so a 70-line invoice fits the
model's context.

### Likely interview questions

**Q: Is the rules tier not just fitted to your own synthetic layouts?**
A: That is the main risk, and it is why the evaluation also reports a
model-only run and results per tier. The labels are general accounting
vocabulary, but on unseen real layouts I would expect the rules to accept
fewer invoices and the model to do more of the work.

**Q: What happens if the model is down?**
A: The extract task retries with backoff (2, 4, 8 seconds). After the last
retry it uses the rules result with every confidence capped at 0.5, so the
invoice is saved but goes to review. Tested in
`test_api.py::test_model_outage_falls_back_to_rules`.

---

## 7. Validation, duplicates and corrections

Code: `backend/app/pipeline/validate.py`, `matching.py`, `backend/app/services.py`.

**Errors versus warnings.** Errors (missing required field, totals that do
not add up, a cross-document mismatch) block approval. Warnings (low
confidence, a line amount off, a tax rate that does not match) send the
invoice to review but can be approved. A reviewer can also explicitly
accept known errors, for example a supplier's arithmetic mistake, and that
decision is recorded.

**Match key.** Supplier name in lower case without punctuation or legal
suffixes, plus the invoice number without separators or leading zeros:
"Padma Trading Co." with "INV-0042" and "PADMA TRADING" with "inv 42" give
the same key.

**After a correction**, the invoice is validated again, issues that no
longer apply are marked resolved (kept for the record), the change is
written to `corrections`, and any group it belongs to is compared again.

---

## 8. Testing

Code: `backend/tests/`. Results: `evaluation/test-results/`.

**Real database, mock model.** Tests run against real PostgreSQL with
pgvector, because full-text search, vector search and constraints cannot be
tested on a fake database. The model is mocked so tests need no GPU and
give the same result every time; the real model is measured by the
evaluation instead.

**Eager Celery.** In tests, tasks run inline, so an upload is fully
processed before the response returns and the test can check the result
straight away.

**Fixtures from known truth.** Test files are generated from known invoices
with the dataset generator, so every test compares against exact values.

**Coverage** is the share of code lines the tests execute: 92%. It shows
what is exercised, not that it is correct; the assertions do that.
