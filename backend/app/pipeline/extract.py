"""Stage 3: turn each invoice's text into fields, choosing between the tiers.

Decision for each invoice:

1. Run the rules. If every required field was found and all the
   arithmetic agrees, accept: method "rules", no model call.
2. Otherwise ask the model. Then merge field by field:
   - both agree           -> keep, high confidence
   - only one has a value -> keep it, with that source's confidence
   - they disagree        -> for the money fields, keep whichever set makes
                             the arithmetic agree; otherwise take the
                             model's value with low confidence, so a person
                             checks it
3. If the model is unavailable, the caller retries the task; after the
   last retry the rules result is used and marked low confidence.

For scanned pages, confidence is capped by the OCR confidence of the page,
so a badly read scan always goes to review.
"""

from __future__ import annotations

import copy
from decimal import Decimal

from .llm import LLMClient, llm_extract
from .rules import arithmetic_consistent, extract_rules
from .schema import ExtractedInvoice, HEADER_FIELDS, MONEY_FIELDS

AGREE = 0.97
DISAGREE = 0.45


def _eq(a, b) -> bool:
    if a is None or b is None:
        return False
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.lower().split()) == " ".join(b.lower().split())
    return a == b


def _lines_ok(inv: ExtractedInvoice) -> bool:
    if not inv.line_items or inv.subtotal is None:
        return False
    if any(li.amount is None for li in inv.line_items):
        return False
    return abs(sum(li.amount for li in inv.line_items) - inv.subtotal) <= Decimal("0.01")


def extract_invoice(text: str, client: LLMClient | None, *, page_texts: list[str] | None = None,
                    ocr_confidence: float | None = None, force_llm: bool = False,
                    llm_only: bool = False) -> ExtractedInvoice:
    rules = extract_rules(text)
    if llm_only:
        result = llm_extract(text, client, page_texts)
    elif not force_llm and not rules.missing() and arithmetic_consistent(rules):
        result = rules
    elif client is None:
        result = rules
        for f in list(result.confidence):
            result.confidence[f] = min(result.confidence[f], 0.5)
        result.warnings.append({"code": "low_confidence", "field": None,
                                "message": "Language model unavailable; rules-only result needs checking"})
    else:
        model = llm_extract(text, client, page_texts)
        result = merge(rules, model)

    if ocr_confidence is not None:
        # On scans the supplier is usually guessed from the first readable line,
        # and the evaluation showed that guess is wrong often enough (for example
        # when the name sits on a dark band OCR cannot read) to be the main source
        # of silent errors. A guessed supplier on OCR text is therefore always reviewed.
        for f in rules.guessed:
            if f in result.confidence and getattr(result, f) == getattr(rules, f):
                result.confidence[f] = min(result.confidence[f], 0.55)
        cap = max(0.3, min(1.0, ocr_confidence / 100 + 0.1))
        for f in list(result.confidence):
            result.confidence[f] = round(min(result.confidence[f], cap), 3)
    return result


def merge(rules: ExtractedInvoice, model: ExtractedInvoice) -> ExtractedInvoice:
    out = copy.deepcopy(rules)
    out.raw_model_output = model.raw_model_output
    out.warnings = rules.warnings + model.warnings
    used_model = False
    conflicts = {}

    for f in HEADER_FIELDS:
        r, m = getattr(rules, f), getattr(model, f)
        if r is None and m is None:
            continue
        if _eq(r, m):
            out.confidence[f] = AGREE
        elif r is None:
            setattr(out, f, m)
            out.confidence[f] = model.confidence.get(f, 0.8)
            out.evidence[f] = model.evidence.get(f, "")
            used_model = True
        elif m is None:
            pass  # keep the rules value and its confidence
        else:
            conflicts[f] = (r, m)

    # money conflicts: prefer the reading that makes the sums agree
    money_conf = {f for f in conflicts if f in MONEY_FIELDS}
    if money_conf:
        trial = copy.deepcopy(out)
        for f in money_conf:
            setattr(trial, f, conflicts[f][1])
        rules_ok, model_ok = arithmetic_consistent(out), arithmetic_consistent(trial)
        for f in money_conf:
            if model_ok and not rules_ok:
                setattr(out, f, conflicts[f][1])
                out.confidence[f] = 0.85
                out.evidence[f] = model.evidence.get(f, "")
                used_model = True
            elif rules_ok and not model_ok:
                out.confidence[f] = 0.85
            else:
                _flag_conflict(out, f, *conflicts[f], model)
                used_model = True
    for f in set(conflicts) - money_conf:
        _flag_conflict(out, f, *conflicts[f], model)
        used_model = True

    # line items: keep the list whose total matches the subtotal
    if not _lines_ok(rules) and model.line_items:
        trial = copy.deepcopy(out)
        trial.line_items = model.line_items
        if _lines_ok(trial) or len(model.line_items) > len(rules.line_items):
            out.line_items = model.line_items
            out.confidence["line_items"] = 0.85 if _lines_ok(trial) else DISAGREE
            used_model = True
    elif rules.line_items and model.line_items and len(rules.line_items) == len(model.line_items):
        out.confidence["line_items"] = AGREE

    out.method = "llm" if used_model else "rules"
    return out


def _flag_conflict(out: ExtractedInvoice, f: str, r, m, model: ExtractedInvoice) -> None:
    setattr(out, f, m)
    out.confidence[f] = DISAGREE
    out.evidence[f] = model.evidence.get(f, "")
    out.warnings.append({"code": "low_confidence", "field": f,
                         "message": f"Rules read '{r}' but the model read '{m}'; please check",
                         "details": {"rules": str(r), "model": str(m)}})
