"""Run the labelled dataset through the live system and measure it.

Uploads every document through the public API (exactly as a user would),
waits for processing to finish, then compares what the system extracted
and flagged with the ground-truth labels.

    python evaluation/run_eval.py --api http://localhost:8000 --key <API key> --label hybrid

Run it against an empty database (for example after `docker compose down -v`),
because duplicate detection looks at every invoice in the database.

Writes evaluation/runs/<label>/metrics.json and report.md.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
FIELDS = ("invoice_number", "invoice_date", "supplier_name", "customer_name",
          "subtotal", "tax", "total", "currency")
MONEY = {"subtotal", "tax", "total"}


# -- comparison helpers ----------------------------------------------------------
def norm(field, v):
    if v is None or v == "":
        return None
    if field in MONEY:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    if field in ("supplier_name", "customer_name"):
        return " ".join(str(v).lower().replace(".", "").split())
    if field == "invoice_number":
        return str(v).strip().upper()
    return str(v)


def field_outcome(field, pred, truth) -> str:
    p, t = norm(field, pred), norm(field, truth)
    if t is None:
        return "correct_null" if p is None else "invented"
    if p is None:
        return "missed"
    return "correct" if p == t else "wrong"


def line_key(li):
    amt = li.get("amount")
    return (" ".join((li.get("description") or "").lower().split()),
            None if amt is None else Decimal(str(amt)).quantize(Decimal("0.01")))


def line_scores(pred: list, truth: list) -> tuple[int, int, int]:
    """(matched, predicted, expected) using description and amount."""
    tp = Counter(line_key(x) for x in pred)
    tt = Counter(line_key(x) for x in truth)
    return sum((tp & tt).values()), len(pred), len(truth)


def match_invoices(preds: list[dict], truths: list[dict]) -> list[tuple[dict | None, dict]]:
    """Pair each true invoice with the extracted invoice that agrees on most fields."""
    pairs, used = [], set()
    for t in truths:
        best, best_score = None, -1
        for i, p in enumerate(preds):
            if i in used:
                continue
            score = sum(field_outcome(f, p.get(f), t[f]) in ("correct", "correct_null") for f in FIELDS)
            if norm("invoice_number", p.get("invoice_number")) == norm("invoice_number", t["invoice_number"]) \
                    and t["invoice_number"]:
                score += 5
            if score > best_score:
                best, best_score = i, score
        if best is not None and best_score >= 2:
            used.add(best)
            pairs.append((preds[best], t))
        else:
            pairs.append((None, t))
    return pairs


def iso(s: str) -> datetime:
    # Python 3.10 does not accept a trailing "Z" for UTC
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def pct(a, b):
    return None if not b else round(100 * a / b, 1)


# -- API client --------------------------------------------------------------------
class Api:
    def __init__(self, base: str, key: str):
        self.c = httpx.Client(base_url=base.rstrip("/") + "/api/v1", headers={"X-API-Key": key}, timeout=300)

    def get(self, path, retries: int = 30, **params):
        # the API can be briefly unavailable while the machine is busy with OCR and
        # the model; wait and retry instead of abandoning a long evaluation run
        for attempt in range(retries):
            try:
                r = self.c.get(path, params=params)
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status is not None and status < 500:
                    raise
                if attempt == retries - 1:
                    raise
                print(f"\n  API not responding ({type(e).__name__}); retrying in 10 s")
                time.sleep(10)

    def all_documents(self) -> list[dict]:
        out, page = [], 1
        while True:
            d = self.get("/documents", page_size=100, page=page)
            out += d["items"]
            if page * 100 >= d["total"]:
                return out
            page += 1

    def upload(self, paths: list[Path]) -> dict:
        files = [("files", (p.name, p.open("rb"))) for p in paths]
        try:
            r = self.c.post("/documents", files=files)
        finally:
            for _, (_, fh) in files:
                fh.close()
        r.raise_for_status()
        return r.json()


# -- main ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--key", required=True)
    ap.add_argument("--data", default=str(HERE / "dataset" / "data"))
    ap.add_argument("--split", default="test", choices=["test", "dev", "all"])
    ap.add_argument("--label", default="run")
    ap.add_argument("--timeout-min", type=int, default=240)
    ap.add_argument("--resume", action="store_true",
                    help="do not upload; use the documents already in the system (after an interrupted run)")
    a = ap.parse_args()

    data = Path(a.data)
    labels = [json.loads(p.read_text()) for p in sorted((data / "labels").glob("*.json"))]
    groups = json.loads((data / "groups.json").read_text())
    # cross-check pairs are kept whole so both halves are always uploaded together
    in_pair = {d for g in groups for d in g["docs"]}
    chosen = [l for l in labels if a.split == "all" or l["split"] == a.split or l["doc_id"] in in_pair]
    api = Api(a.api, a.key)
    print(f"{len(chosen)} documents ({a.split} split plus all cross-check pairs)")

    # 1. upload (or, with --resume, find the documents uploaded by the interrupted run)
    t0 = time.perf_counter()
    doc_of: dict[str, str] = {}
    if a.resume:
        by_name = {d["filename"]: d["id"] for d in api.all_documents()}
        for l in chosen:
            name = l["file"].split("/")[-1]
            if name in by_name:
                doc_of[l["doc_id"]] = by_name[name]
        print(f"resuming: found {len(doc_of)} of {len(chosen)} documents already uploaded")
        chosen = [l for l in chosen if l["doc_id"] in doc_of]
    for i in range(0, len(chosen) if not a.resume else 0, 20):
        batch = chosen[i:i + 20]
        res = api.upload([data / l["file"] for l in batch])
        names = {l["file"].split("/")[-1]: l["doc_id"] for l in batch}
        for acc in res["accepted"]:
            doc_of[names[acc["filename"]]] = acc["id"]
        for rej in res["rejected"]:
            print("rejected at upload:", rej)
    upload_s = time.perf_counter() - t0
    print(f"uploaded in {upload_s:.1f} s; waiting for processing")

    # 2. wait
    pending = set(doc_of.values())
    deadline = time.time() + a.timeout_min * 60
    while pending and time.time() < deadline:
        time.sleep(5)
        busy = {d["id"] for d in api.all_documents() if d["status"] in ("queued", "processing")} & pending
        pending = busy
        print(f"  {len(busy)} still processing", end="\r")
    wall_s = time.perf_counter() - t0
    if a.resume:
        print("note: with --resume, wall-clock time covers only the resumed part; "
              "use the per-document stage timings for speed")
    print(f"\nall finished in {wall_s:.0f} s" if not pending else f"\nTIMED OUT with {len(pending)} pending")

    # 3. collect
    docs = {}
    for doc_label, sid in doc_of.items():
        d = api.get(f"/documents/{sid}")
        d["invoice_details"] = [api.get(f"/invoices/{i['id']}") for i in d["invoices"]]
        docs[doc_label] = d

    # wall-clock time from the first upload to the last finished document, taken
    # from the server's own timestamps so it is also right after --resume
    starts = [iso(d["uploaded_at"]) for d in docs.values()]
    ends = [iso(d["last_run"]["finished_at"]) for d in docs.values()
            if d.get("last_run") and d["last_run"].get("finished_at")]
    if starts and ends:
        wall_s = (max(ends) - min(starts)).total_seconds()

    # 4. score
    lab = {l["doc_id"]: l for l in labels}
    m = {"label": a.label, "split": a.split, "documents": len(chosen),
         "date": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    fields = defaultdict(Counter)
    by = {k: defaultdict(lambda: defaultdict(Counter)) for k in ("format", "degradation", "locale", "method")}
    inv_total = inv_found = inv_all_correct = 0
    lines = [0, 0, 0]
    flags = defaultdict(Counter)
    silent_errors = review_total = 0
    silent_cases = []
    status_ok = status_total = fail_ok = fail_total = false_fail = 0
    fail_codes = Counter()
    per_page_ms = defaultdict(list)
    doc_ms = []
    methods = Counter()

    for did, d in docs.items():
        L = lab[did]
        run = d.get("last_run") or {}
        if run.get("stage_timings_ms"):
            # processing time only, excluding time spent waiting in the queue
            ms = sum(run["stage_timings_ms"].values())
            doc_ms.append(ms)
            if d.get("page_count"):
                per_page_ms[L["format"]].append(ms / d["page_count"])
        if L["expected_status"] == "failed":
            fail_total += 1
            if d["status"] == "failed":
                fail_codes[(L["expected_error"], d["error_code"])] += 1
                fail_ok += d["error_code"] == L["expected_error"] or (
                    L["expected_error"] in ("corrupted", "empty_file") and d["error_code"] in ("corrupted", "empty_file"))
            continue
        status_total += 1
        if d["status"] in ("completed", "needs_review") and d["invoices"]:
            status_ok += 1
        if d["status"] == "failed":
            false_fail += 1

        preds = d["invoice_details"]
        truths = [i["ground_truth"] | {"_flags": i["expected_flags"], "_locale": i["locale"]} for i in L["invoices"]]
        for p, t in match_invoices(preds, truths):
            inv_total += 1
            meta = {"format": L["format"], "degradation": L["degradation"] or "none", "locale": t["_locale"],
                    "method": (p or {}).get("extraction_method", "not found")}
            if p is None:
                for f in FIELDS:
                    fields[f]["missed" if t[f] is not None else "correct_null"] += 1
                lines[2] += len(t["line_items"])
                for k, v in meta.items():
                    by[k][v]["invoices"]["total"] += 1
                continue
            inv_found += 1
            methods[p["extraction_method"]] += 1
            all_ok = True
            for f in FIELDS:
                o = field_outcome(f, p.get(f), t[f])
                fields[f][o] += 1
                ok = o in ("correct", "correct_null")
                all_ok &= ok
                for k, v in meta.items():
                    by[k][v]["fields"]["correct" if ok else "wrong"] += 1
            mt, pp, tt = line_scores(p["line_items"], t["line_items"])
            lines[0] += mt; lines[1] += pp; lines[2] += tt
            all_ok &= (mt == pp == tt)
            inv_all_correct += all_ok
            for k, v in meta.items():
                by[k][v]["invoices"]["total"] += 1
                by[k][v]["invoices"]["fully_correct"] += all_ok
            # an invoice with any wrong value that was approved automatically is a silent error
            review_total += 1
            if not all_ok and p["review_status"] == "auto_approved":
                silent_errors += 1
                wrong = [f for f in FIELDS if field_outcome(f, p.get(f), t[f]) not in ("correct", "correct_null")]
                if mt != tt or pp != tt:
                    wrong.append("line_items")
                silent_cases.append({"doc": did, "format": L["format"], "degradation": L["degradation"],
                                     "wrong": {f: [p.get(f), t[f]] for f in wrong if f != "line_items"},
                                     "line_items": wrong[-1] == "line_items" if wrong else False})
            # validation flags
            got = set()
            for i in p["issues"]:
                if i["resolved"]:
                    continue
                if i["code"] == "missing_field":
                    got.add(f"missing:{i['field']}")
                elif i["code"] == "cross_mismatch":
                    got.add(f"cross_mismatch:{i['field']}")
                else:
                    got.add(i["code"])
            want = set(t["_flags"])
            for code in {f.split(":")[0] for f in want | got}:
                w = {f for f in want if f.split(":")[0] == code}
                g = {f for f in got if f.split(":")[0] == code}
                flags[code]["tp"] += len(w & g)
                flags[code]["fn"] += len(w - g)
                flags[code]["fp"] += len(g - w)
                # a flag on a misread invoice is doing its job (sending a wrong reading
                # to review); a flag on a correctly read invoice is a true false alarm
                flags[code]["false_alarm"] += len(g - w) if all_ok else 0

    # groups (duplicates and cross-checks)
    found_groups = api.get("/groups", page_size=100)["items"]
    sid_to_label = {v: k for k, v in doc_of.items()}
    found_pairs = {}
    for g in found_groups:
        key = frozenset(sid_to_label.get(mb["document_id"]) for mb in g["members"])
        found_pairs[key] = set(g["mismatched_fields"])
    g_hit = g_exact = 0
    expected_groups = [g for g in groups if all(x in doc_of for x in g["docs"])]
    for g in expected_groups:
        key = frozenset(g["docs"])
        if key in found_pairs:
            g_hit += 1
            g_exact += found_pairs[key] == set(g["expected_mismatches"])
    extra_groups = len([k for k in found_pairs if k not in {frozenset(g["docs"]) for g in expected_groups}])

    # API latency
    lat = {}
    for name, path, params in (("status", "/documents", {"page_size": 25}),
                               ("search_keyword", "/search", {"q": "services", "mode": "keyword"}),
                               ("search_hybrid", "/search", {"q": "office supplies", "mode": "hybrid"})):
        ts = []
        for _ in range(10):
            t = time.perf_counter()
            api.get(path, **params)
            ts.append((time.perf_counter() - t) * 1000)
        lat[name] = round(st.median(ts), 1)

    total_fields = sum(sum(c.values()) for c in fields.values())
    correct_fields = sum(c["correct"] + c["correct_null"] for c in fields.values())
    invented = sum(c["invented"] for c in fields.values())
    nulls = sum(c["invented"] + c["correct_null"] for c in fields.values())
    pages = sum((docs[d].get("page_count") or 0) for d in docs)
    m.update({
        "wall_clock_s": round(wall_s, 1),
        "throughput_docs_per_hour": round(len(docs) / wall_s * 3600),
        "throughput_pages_per_hour": round(pages / wall_s * 3600),
        "median_doc_seconds": round(st.median(doc_ms) / 1000, 2) if doc_ms else None,
        "median_ms_per_page_by_format": {k: round(st.median(v)) for k, v in sorted(per_page_ms.items())},
        "document_success_rate": pct(status_ok, status_total),
        "document_failure_rate_unexpected": pct(false_fail, status_total),
        "bad_files_rejected_correctly": pct(fail_ok, fail_total),
        "bad_file_outcomes": {f"{e} -> {g}": n for (e, g), n in fail_codes.items()},
        "invoices_expected": inv_total, "invoices_found": inv_found,
        "invoice_detection_rate": pct(inv_found, inv_total),
        "field_accuracy": pct(correct_fields, total_fields),
        "field_accuracy_by_field": {f: pct(c["correct"] + c["correct_null"], sum(c.values())) for f, c in fields.items()},
        "field_outcomes": {f: dict(c) for f, c in fields.items()},
        "invented_value_rate": pct(invented, nulls),
        "invoices_fully_correct": pct(inv_all_correct, inv_total),
        "line_item_precision": pct(lines[0], lines[1]), "line_item_recall": pct(lines[0], lines[2]),
        "silent_error_rate": pct(silent_errors, review_total),
        "silent_error_cases": silent_cases,
        "extraction_method": dict(methods),
        "validation_flags": {k: {**v, "precision": pct(v["tp"], v["tp"] + v["fp"]),
                                 "recall": pct(v["tp"], v["tp"] + v["fn"])} for k, v in sorted(flags.items())},
        "groups_expected": len(expected_groups), "groups_found": g_hit,
        "groups_with_exact_mismatch_fields": g_exact, "unexpected_groups": extra_groups,
        "api_median_latency_ms": lat,
        "breakdown": {k: {v: {"field_accuracy": pct(c["fields"]["correct"], sum(c["fields"].values())),
                              "invoices": c["invoices"]["total"],
                              "fully_correct": pct(c["invoices"]["fully_correct"], c["invoices"]["total"])}
                          for v, c in sorted(b.items())} for k, b in by.items()},
    })
    out = HERE / "runs" / a.label
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(m, indent=2, default=str))
    (out / "report.md").write_text(render(m))
    print((out / "report.md").read_text())


def render(m: dict) -> str:
    r = [f"# Evaluation run: {m['label']}", "",
         f"{m['date']} · {m['documents']} documents ({m['split']} split plus cross-check pairs)", "",
         "| Metric | Value |", "|---|---|"]
    rows = [
        ("Document success rate (readable files processed)", f"{m['document_success_rate']}%"),
        ("Unexpected failure rate (readable files that failed)", f"{m['document_failure_rate_unexpected']}%"),
        ("Bad files rejected with the right reason", f"{m['bad_files_rejected_correctly']}%"),
        ("Invoices detected", f"{m['invoices_found']} of {m['invoices_expected']} ({m['invoice_detection_rate']}%)"),
        ("Field accuracy (8 header fields)", f"{m['field_accuracy']}%"),
        ("Invoices with every field and line correct", f"{m['invoices_fully_correct']}%"),
        ("Line items: precision / recall", f"{m['line_item_precision']}% / {m['line_item_recall']}%"),
        ("Invented values (a value returned where the document has none)", f"{m['invented_value_rate']}%"),
        ("Silent errors (wrong but auto-approved)", f"{m['silent_error_rate']}%"),
        ("Duplicate and cross-check groups found", f"{m['groups_found']} of {m['groups_expected']} "
                                                   f"({m['groups_with_exact_mismatch_fields']} with exactly the right differing fields; "
                                                   f"{m['unexpected_groups']} unexpected)"),
        ("Total processing time", f"{m['wall_clock_s']} s"),
        ("Throughput", f"{m['throughput_docs_per_hour']} documents/hour, {m['throughput_pages_per_hour']} pages/hour"),
        ("Median time per document", f"{m['median_doc_seconds']} s"),
    ]
    r += [f"| {a} | {b} |" for a, b in rows]
    r += ["", "## Field accuracy by field", "", "| Field | Accuracy |", "|---|---|"]
    r += [f"| {f} | {v}% |" for f, v in m["field_accuracy_by_field"].items()]
    for k in ("format", "degradation", "locale", "method"):
        r += ["", f"## By {k}", "", f"| {k} | Invoices | Field accuracy | Fully correct |", "|---|---|---|---|"]
        r += [f"| {v} | {x['invoices']} | {x['field_accuracy']}% | {x['fully_correct']}% |"
              for v, x in m["breakdown"][k].items()]
    r += ["", "## Validation flags", "",
          "Expected flags come from the labels. An unexpected flag on a misread invoice is the system",
          "correctly catching its own reading error; only unexpected flags on correctly read invoices",
          "are false alarms.", "",
          "| Flag | Precision | Recall | Expected and raised | Unexpected | of which false alarms | Missed |",
          "|---|---|---|---|---|---|---|"]
    r += [f"| {k} | {v['precision']}% | {v['recall']}% | {v.get('tp', 0)} | {v.get('fp', 0)} | {v.get('false_alarm', 0)} | {v.get('fn', 0)} |"
          for k, v in m["validation_flags"].items()]
    r += ["", "## Speed", "", "| Format | Median ms per page |", "|---|---|"]
    r += [f"| {k} | {v} |" for k, v in m["median_ms_per_page_by_format"].items()]
    r += ["", "API median latency (ms): " + ", ".join(f"{k} {v}" for k, v in m["api_median_latency_ms"].items()),
          "", "Extraction method counts: " + ", ".join(f"{k} {v}" for k, v in m["extraction_method"].items()),
          "", "Bad file outcomes (expected -> actual): " + ", ".join(f"{k}: {v}" for k, v in m["bad_file_outcomes"].items())]
    return "\n".join(r) + "\n"


if __name__ == "__main__":
    main()
