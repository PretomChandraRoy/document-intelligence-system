# Evaluation dataset

A synthetic, fully labelled set of business documents used to measure the
system's extraction accuracy, validation accuracy, speed and failure handling.

**Why synthetic.** No labelled real invoices were available, and real
invoices contain personal and commercial data. Generating the documents
from known values gives exact ground truth for every field. The limitation
is that synthetic layouts are cleaner and more regular than real supplier
invoices, so the measured accuracy should be read as an upper bound on
real-world performance.

## Reproduce

```bash
cd evaluation/dataset
pip install -r requirements.txt
python -m gen.build --out data --seed 42      # about 10 seconds
python -m gen.verify data                     # checks every label against its file
python -m gen.stress --pages 1000 --scanned-fraction 0.2 --out data_stress   # optional, about 100 MB
```

The same seed always produces the same files and labels.

## Composition (seed 42)

| | Count |
|---|---|
| Documents | 219 |
| Invoices (some documents hold several) | 261 |
| Line items | 1,709 |
| Dev / test split | 76 / 143 documents |

| Format | Documents | Notes |
|---|---|---|
| Digital PDF | 74 | Text layer present; 4 layouts; includes long multi-page invoices and a 10-invoice bundle |
| Scanned PDF | 21 | Image-only pages, no text layer; includes multi-page scans and an 8-invoice bundle |
| JPG | 24 | Photos and scans at four quality levels |
| PNG | 24 | As above |
| TIFF | 15 | Includes 3 multi-page TIFFs |
| XLSX | 24 | Form, multi-sheet and ledger layouts |
| XLS | 15 | Legacy Excel format |
| CSV | 19 | Comma and semicolon dialects, dot and comma decimals |
| Mixed PDF | 3 | Digital and scanned pages in the same file, including a 3-invoice bundle |

**Image quality levels** (scans and photos): clean 15, mild 33, moderate 26, severe 11.
"Severe" means about 110 dpi with strong blur, noise, skew and faded ink.

**Locales**, which control currency, tax and formatting habits:

| Locale | Invoices | Formats seen |
|---|---|---|
| Bangladesh | 74 | BDT, Tk or BDT symbol, VAT 15/7.5/5%, Indian digit grouping (1,23,456.00), day-first dates |
| US home care billing | 63 | USD, hourly care services, service periods, usually no tax line |
| United States | 45 | USD, sales tax, month-first dates |
| United Kingdom | 45 | GBP, VAT 20% |
| Eurozone | 34 | EUR, VAT 19/21%, comma decimals (1.234,56), dotted dates |

## Deliberate edge cases

| Case | Count | What a correct system does |
|---|---|---|
| Total does not equal subtotal plus tax | 14 (+2 in records) | Flag `total_mismatch` |
| Line items do not add up to subtotal | 8 | Flag `line_items_mismatch` |
| A line amount is not quantity times price | 6 | Flag `line_amount_mismatch` |
| Missing invoice date / customer / number / currency | 7 / 6 / 4 / 22 | Return `null` for the field and flag `missing:<field>`; never invent a value |
| No tax line printed | 54 | Return `tax: null`, not `0` |
| Same invoice submitted twice (PDF re-sent as photo or scan) | 6 pairs | Flag `duplicate` |
| PDF invoice vs its spreadsheet accounting record | 10 pairs (3 disagree) | Cross-verify and flag `cross_mismatch:<field>` where they differ |
| PDF supplier copy vs PDF internal copy | 5 pairs (3 disagree) | As above |
| Several invoices in one PDF | 3 files, 21 invoices | Split by invoice and extract each |
| Spreadsheets holding several invoices | 8 files | Group rows by invoice |
| Corrupted, empty, encrypted or data-less files | 8 | Fail cleanly with a clear error, never a partial result |

162 of the 261 invoices are clean and should raise no flags; this measures
false alarms.

## Label format

`data/labels/<doc_id>.json`:

```json
{
  "doc_id": "d012",
  "file": "files/d012.pdf",
  "format": "pdf_digital",
  "layout": "classic",
  "degradation": null,
  "pages": 2,
  "split": "test",
  "expected_status": "completed",
  "expected_error": null,
  "invoices": [{
    "invoice_id": "inv0012",
    "locale": "us",
    "defects": [],
    "ground_truth": {
      "invoice_number": "BD/26-27/6884",
      "invoice_date": "2026-02-01",
      "supplier_name": "Rodriguez, Figueroa and Sanchez",
      "customer_name": "Matthew Gardner",
      "subtotal": "...", "tax": "...", "total": "...",
      "currency": "USD",
      "line_items": [{"description": "...", "quantity": "1", "unit_price": "5.12", "amount": "5.12"}]
    },
    "expected_flags": []
  }]
}
```

Money values are strings so that no precision is lost. `null` means the
value is not printed on the document. Ground truth is always what is
**printed**, even when the printed arithmetic is wrong; catching the error
is the validator's job, not the extractor's.

`data/groups.json` lists documents that contain the same invoice, with the
fields on which they disagree. `data/manifest.csv` has one row per document.

## Known limitations

- Four layout families only; real suppliers use far more.
- Scan degradation is simulated (skew, blur, noise, shadow, JPEG
  compression). Real photos also have perspective distortion, folds and
  handwriting, which are not modelled.
- Names and addresses are generated by the Faker library and are fictional.
- English-language documents only; no Bangla script.
