"""Split a multi-page document into invoices.

A 1,000-page PDF is usually many invoices back to back. A page starts a new
invoice when it says "Page 1 of N", or when it carries an invoice number
different from the current invoice's. A page that says "continued" or
"Page 2 of N" stays with the invoice before it. Pages with no readable text
stay with the invoice before them, so nothing is silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rules import extract_rules

PAGE_OF = re.compile(r"page\s*(\d+)\s*(?:of|/)\s*(\d+)", re.I)
CONTINUED = re.compile(r"\(continued\)|continued from", re.I)


@dataclass
class Segment:
    pages: list[int] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    invoice_number: str | None = None

    @property
    def start(self) -> int:
        return self.pages[0]

    @property
    def end(self) -> int:
        return self.pages[-1]

    @property
    def text(self) -> str:
        return "\n\n".join(t for t in self.texts if t)


def page_invoice_number(text: str) -> str | None:
    """The invoice number printed in the top part of the page, if any."""
    head = "\n".join(text.splitlines()[:25])
    return extract_rules(head).invoice_number if head.strip() else None


def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]:
    segments: list[Segment] = []
    for number, text in pages:
        text = text or ""
        m = PAGE_OF.search(text)
        k = int(m.group(1)) if m else None
        num = page_invoice_number(text)
        cur = segments[-1] if segments else None

        if cur is None:
            new = True
        elif k is not None:
            new = k == 1
        elif CONTINUED.search(text):
            new = False
        elif num and cur.invoice_number and num != cur.invoice_number:
            new = True
        else:
            new = False

        if new:
            segments.append(Segment([number], [text], num))
        else:
            cur.pages.append(number)
            cur.texts.append(text)
            if cur.invoice_number is None and num:
                cur.invoice_number = num
    return segments
