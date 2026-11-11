# AI disclosure

This project was built with substantial AI assistance. This document states
which AI tools were used, what each party did, and where the prompts are, as
required by deliverable 9 of the brief.

## 1. AI used during development

| | |
|---|---|
| Tool | Claude by Anthropic, used through the Claude app in a session with its own cloud workspace (file editing, shell, Git) |
| Period | 7 to 11 November 2026 |
| Extent | Claude wrote most of the code and documentation |

### What Claude did

- Proposed the architecture, the technology choices and the evaluation
  method, with the reasoning for each, for approval before building.
- Wrote the code: backend (API, pipeline, workers, database migrations),
  frontend, dataset generator, automated tests, evaluation runner, Docker set-up.
- Wrote the documentation, diagrams and this repository's reports, including
  a learning guide (`docs/LEARNING.md`) explaining the concepts and decisions.
- Analysed the evaluation output, found errors in the system and in the
  evaluation script, and fixed them.
- Gave step-by-step instructions for setting up and running the system on
  the desktop.

### What Pretom Chandra Roy did

- Set the requirements and constraints: no budget, a local Windows desktop
  (Ryzen 5 5500, 16 GB RAM, RTX 3050 8 GB), Python for the backend and Next.js
  for the frontend.
- Chose between the options presented, approved each design and document
  before it was written, and directed the order of work (for example, building
  the frontend one screen at a time).
- Set up and ran the system on the desktop: Docker Desktop, Ollama and the
  models, and enabling CPU virtualisation in the BIOS.
- Ran every evaluation with the real model, reported problems (a crash during
  a long run, evaluation errors) and the raw results, and agreed the method
  for handling them (the test run frozen as the official result, known issues
  reported rather than tuned away, and a rules-first versus model-only
  comparison on the development split).
- Reviewed the running application, the screens, and the results.

### How AI output was checked

Nothing was accepted on the strength of the AI's own claims. The code is
covered by 142 automated tests; every reported figure comes from a recorded
evaluation run against labelled data; and the application was run and used on
the target desktop. This process caught real mistakes, including AI-written
ones: for example, the evaluation script read the answer key with the wrong
text encoding on Windows, which was found while checking individual errors
and corrected before the results were reported (see the
[evaluation report](../evaluation/REPORT.md), section 2.5).

No real invoice or personal data was used during development; all test and
evaluation documents are synthetic.

## 2. AI used by the system at run time

| Model | Purpose | Where it runs |
|---|---|---|
| `qwen3:8b` (4-bit) | Extracting invoice fields when the rules cannot | Locally through Ollama, on the GPU |
| `nomic-embed-text` | Embeddings for semantic search | Locally through Ollama |

No document content is sent to any external service.

The prompts and the output schema the system sends to the model are in
[`backend/app/prompts/`](../backend/app/prompts/):

| File | Purpose |
|---|---|
| `extraction_system.md` | Instructions: extract only what is printed, return `null` otherwise, quote the source text for each value |
| `extraction_user.md` | The invoice text and the request for the header fields and line items |
| `line_items_user.md` | Line items for one page of a long invoice, processed in parts |
| `invoice_schema.json` | JSON schema that constrains the model's output |

The model is called with temperature 0 and with reasoning mode off, so the
same input gives the same output. Every value it returns is checked against
the source text and discarded if it cannot be found there.

## 3. Main development prompts

A summary of the instructions given to Claude during development, in order.
They are paraphrased; the conversations themselves are not included.

| Stage | Instruction |
|---|---|
| Planning | Help with the whole application: the assessment system, CV, portfolio and reply. Zero budget; build on the Windows desktop; recommend local model or free API, and the backend framework |
| Planning | Write the code, but explain the concepts and decisions while working (the learning guide) |
| Planning | Read the brief again and check that the plan meets every requirement |
| Dataset | Generate a labelled evaluation dataset, since no labelled invoices are available |
| Design | Write the architecture, database and API documents before building |
| Backend | Build the processing pipeline, API, database and tests |
| Frontend | Build the frontend one screen at a time; do not commit until told to |
| Running | Step-by-step instructions to run the system on the desktop; diagnose Docker, virtualisation and evaluation problems from the outputs sent back |
| Evaluation | Freeze the test run as the official result, list the known issues, and compare rules-first with model-only on the development split |
| Documentation | Check the brief again, then write the evaluation report, README and this disclosure from approved outlines |
