export function money(v: string | null | undefined, currency?: string | null): string {
  if (v === null || v === undefined) return "–";
  const n = Number(v);
  const s = n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${currency} ${s}` : s;
}

export function date(v: string | null | undefined): string {
  if (!v) return "–";
  const d = new Date(v.length === 10 ? `${v}T00:00:00` : v);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return "–";
  return new Date(v).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export const FIELD_LABELS: Record<string, string> = {
  invoice_number: "Invoice number", invoice_date: "Invoice date", supplier_name: "Supplier",
  customer_name: "Customer", subtotal: "Subtotal", tax: "Tax", total: "Total", currency: "Currency",
  line_items: "Line items",
};

export const ISSUE_LABELS: Record<string, string> = {
  missing_field: "Missing field", total_mismatch: "Total mismatch", line_items_mismatch: "Line items mismatch",
  line_amount_mismatch: "Line amount mismatch", tax_rate_mismatch: "Tax rate mismatch",
  implausible_value: "Implausible value", ungrounded_value: "Value not in document",
  low_confidence: "Low confidence", duplicate: "Duplicate", cross_mismatch: "Cross-check mismatch",
};

export const ERROR_LABELS: Record<string, string> = {
  corrupted: "File is corrupted", encrypted: "PDF is password-protected", empty_file: "File is empty",
  no_data: "No data rows", unsupported_format: "Unsupported format", no_invoice_found: "No invoice found",
  internal: "Internal error",
};
