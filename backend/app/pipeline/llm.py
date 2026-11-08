"""Tier 2 extraction: the language model, and the guard against invented values.

The model is called through a small interface (LLMClient) so the provider is
a configuration choice: Ollama locally, a mock in tests, or a hosted API if
data policy ever allows it.

The model is asked to copy values exactly as printed and to quote the text
each value came from. Every answer is then checked against the source text
(`ground`): anything that cannot be found there is discarded, the field
becomes null, and a warning is recorded. The model can therefore leave
gaps, but it cannot add facts that are not in the document.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from .normalise import detect_currency, norm_text, parse_date, parse_money, parse_quantity
from .schema import ExtractedInvoice, ExtractedLine, MONEY_FIELDS

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
SINGLE_CALL_MAX_CHARS = 10_000


# -- output schema the model must follow ----------------------------------------
class Field_(BaseModel):
    value: str | None = Field(description="The value exactly as printed, or null if absent")
    evidence: str | None = Field(description="Shortest exact quote from the text containing the value")


class Line(BaseModel):
    description: str | None
    quantity: str | None
    unit_price: str | None
    amount: str | None


class InvoiceOut(BaseModel):
    invoice_number: Field_
    invoice_date: Field_
    supplier_name: Field_
    customer_name: Field_
    subtotal: Field_
    tax: Field_
    total: Field_
    currency: Field_
    line_items: list[Line]


class HeaderOut(BaseModel):
    invoice_number: Field_
    invoice_date: Field_
    supplier_name: Field_
    customer_name: Field_
    subtotal: Field_
    tax: Field_
    total: Field_
    currency: Field_


class LinesOut(BaseModel):
    line_items: list[Line]


def schema_of(model: type[BaseModel]) -> dict:
    """JSON schema with $ref links expanded, which constrained decoders handle more reliably."""
    sch = model.model_json_schema()
    defs = sch.pop("$defs", {})

    def expand(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return expand(dict(defs[node["$ref"].split("/")[-1]]))
            return {k: expand(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [expand(x) for x in node]
        return node

    return expand(sch)


def prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


# -- clients ----------------------------------------------------------------------
class LLMError(Exception):
    """A temporary failure (timeout, connection); the task should be retried."""


class LLMClient(Protocol):
    name: str

    def chat_json(self, system: str, user: str, schema: dict) -> dict: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaClient:
    name = "ollama"

    def __init__(self, url: str, model: str, embed_model: str, timeout_s: int = 180, num_ctx: int = 8192):
        self.url = url.rstrip("/")
        self.model = model
        self.embed_model = embed_model
        self.timeout = timeout_s
        self.num_ctx = num_ctx

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,           # Ollama structured outputs: constrains decoding to the schema
            "stream": False,
            "think": False,             # Qwen3: skip the reasoning trace, it is slow and not needed here
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "seed": 0},
        }
        try:
            r = httpx.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise LLMError(f"Ollama not reachable: {e}") from e
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama returned {e.response.status_code}: {e.response.text[:200]}") from e
        content = r.json()["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Model output was not valid JSON: {content[:200]}") from e

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = httpx.post(f"{self.url}/api/embed", json={"model": self.embed_model, "input": texts},
                           timeout=self.timeout)
            r.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
            raise LLMError(f"Embedding failed: {e}") from e
        return r.json()["embeddings"]

    def health(self) -> bool:
        try:
            return httpx.get(f"{self.url}/api/tags", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False


class MockClient:
    """Deterministic stand-in for tests and GPU-less demos.

    chat_json answers from a scripted response if one is set, otherwise it
    reads the fields with the rules extractor, so the full pipeline can run
    end to end without a model. embed builds a hashed bag-of-words vector,
    which behaves like a crude semantic embedding.
    """
    name = "mock"
    min_similarity = 0.12  # bag-of-words vectors score lower than real embeddings

    def __init__(self, dim: int = 768):
        self.dim = dim
        self.scripted: list[dict] = []
        self.calls = 0

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        self.calls += 1
        if self.scripted:
            return self.scripted.pop(0)
        from .rules import extract_rules
        text = user.split("<document>")[-1].split("</document>")[0] if "<document>" in user \
            else user.split("<page>")[-1].split("</page>")[0]
        inv = extract_rules(text)
        d = inv.as_dict()
        src = norm_text(text)
        # like a careful model, answer only with values that appear in the text;
        # normalised forms such as ISO dates are not printed, so leave them out
        for f in list(d):
            if f != "line_items" and d[f] is not None and norm_text(d[f]) not in src:
                d[f] = None
        lines = [li for li in d["line_items"] if norm_text(li["description"]) in src]
        if "invoice_number" not in schema.get("properties", {}):
            return {"line_items": lines}
        out = {f: {"value": d[f], "evidence": inv.evidence.get(f)} for f in
               ("invoice_number", "invoice_date", "supplier_name", "customer_name",
                "subtotal", "tax", "total", "currency")}
        if "line_items" in schema.get("properties", {}):
            out["line_items"] = lines
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in re.findall(r"[a-z]{3,}", t.lower()):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    def health(self) -> bool:
        return True


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        from ..config import get_settings
        s = get_settings()
        _client = MockClient(s.embed_dim) if s.llm_provider == "mock" else OllamaClient(
            s.ollama_url, s.llm_model, s.embed_model, s.llm_timeout_s, s.llm_num_ctx)
    return _client


def set_client(c: LLMClient | None) -> None:
    global _client
    _client = c


# -- extraction with the model ------------------------------------------------------
def llm_extract(text: str, client: LLMClient, page_texts: list[str] | None = None) -> ExtractedInvoice:
    system = prompt("extraction_system.md")
    t0 = time.perf_counter()
    if len(text) <= SINGLE_CALL_MAX_CHARS or not page_texts or len(page_texts) < 2:
        raw = client.chat_json(system, prompt("extraction_user.md").replace("{text}", text[:40_000]),
                               schema_of(InvoiceOut))
        raw = InvoiceOut.model_validate(raw).model_dump()
    else:
        # long invoice: header and totals from the first and last pages,
        # then the items table page by page
        head_text = page_texts[0] + "\n\n" + page_texts[-1]
        raw = HeaderOut.model_validate(client.chat_json(
            system, prompt("extraction_user.md").replace("{text}", head_text),
            schema_of(HeaderOut))).model_dump()
        raw["line_items"] = []
        for pt in page_texts:
            part = LinesOut.model_validate(client.chat_json(
                system, prompt("line_items_user.md").replace("{text}", pt),
                schema_of(LinesOut))).model_dump()
            raw["line_items"].extend(part["line_items"])
    inv = ground(raw, text)
    inv.raw_model_output = {"model": getattr(client, "model", client.name), "output": raw,
                            "ms": int((time.perf_counter() - t0) * 1000)}
    return inv


def _found(value: str, source_norm: str) -> bool:
    v = norm_text(value)
    return bool(v) and v in source_norm


def ground(raw: dict, source: str) -> ExtractedInvoice:
    """Convert the model's strings to typed values, keeping only what the text supports."""
    src = norm_text(source)
    inv = ExtractedInvoice(method="llm")
    cur_raw = (raw.get("currency") or {}).get("value")
    currency = detect_currency(cur_raw or "") or (cur_raw.upper() if cur_raw and re.fullmatch(r"[A-Za-z]{3}", cur_raw) else None)
    decimal_comma = currency == "EUR" or None

    for f in ("invoice_number", "invoice_date", "supplier_name", "customer_name",
              "subtotal", "tax", "total", "currency"):
        item = raw.get(f) or {}
        value, evidence = item.get("value"), item.get("evidence")
        if value in (None, "", "null"):
            continue
        if not _found(value, src):
            inv.warnings.append({"code": "ungrounded_value", "field": f,
                                 "message": f"Model returned '{value}' for {f}, which is not in the document; discarded"})
            continue
        if f == "invoice_date":
            d, amb = parse_date(value, currency)
            if d is None:
                continue
            inv.invoice_date = d
            inv.confidence[f] = 0.55 if amb else 0.85
        elif f in MONEY_FIELDS:
            v = parse_money(value, decimal_comma)
            if v is None:
                continue
            setattr(inv, f, v)
            inv.confidence[f] = 0.85
        elif f == "currency":
            if currency is None:
                continue
            inv.currency = currency
            inv.confidence[f] = 0.85
        else:
            setattr(inv, f, value.strip())
            inv.confidence[f] = 0.85
        inv.evidence[f] = evidence if evidence and _found(evidence, src) else value
        if f == "tax" and evidence:
            from .labels import tax_rate_in
            inv.tax_rate = tax_rate_in(evidence)

    dropped = 0
    for li in raw.get("line_items") or []:
        nums_ok = all(_found(li[k], src) for k in ("quantity", "unit_price", "amount") if li.get(k))
        desc_ok = not li.get("description") or _found(li["description"], src)
        if not (nums_ok and desc_ok):
            dropped += 1
            continue
        inv.line_items.append(ExtractedLine(
            (li.get("description") or "").strip() or None,
            parse_quantity(li.get("quantity"), decimal_comma),
            parse_money(li.get("unit_price"), decimal_comma),
            parse_money(li.get("amount"), decimal_comma)))
    if dropped:
        inv.warnings.append({"code": "ungrounded_value", "field": "line_items",
                             "message": f"{dropped} line item(s) returned by the model were not found in the document; discarded"})
    if inv.line_items:
        inv.confidence["line_items"] = 0.85
    return inv
