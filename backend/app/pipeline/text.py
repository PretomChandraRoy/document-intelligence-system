"""Rebuild readable lines from positioned words.

Both PDF text layers and OCR return words with coordinates. Joining them in
reading order, with a wide gap kept as two or more spaces, preserves the
column structure of a table ("Laser Toner  2  500.00  1,000.00") and the
link between a label and its value ("Invoice No:   INV-0042"), which the
rules extractor relies on.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float = 100.0


def lines_from_words(words: list[Word], gap_factor: float = 1.2) -> list[str]:
    if not words:
        return []
    words = sorted(words, key=lambda w: (round((w.y0 + w.y1) / 2), w.x0))
    heights = sorted(w.y1 - w.y0 for w in words)
    h = max(heights[len(heights) // 2], 1.0)

    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.y0 + w.y1) / 2):
        mid = (w.y0 + w.y1) / 2
        if rows:
            last = rows[-1]
            last_mid = sum((x.y0 + x.y1) / 2 for x in last) / len(last)
            if abs(mid - last_mid) <= h * 0.5:
                last.append(w)
                continue
        rows.append([w])

    lines = []
    for row in rows:
        row.sort(key=lambda w: w.x0)
        parts = [row[0].text]
        for prev, cur in zip(row, row[1:]):
            gap = cur.x0 - prev.x1
            parts.append("    " if gap > h * gap_factor else " ")
            parts.append(cur.text)
        lines.append("".join(parts).strip())
    return [ln for ln in lines if ln]
