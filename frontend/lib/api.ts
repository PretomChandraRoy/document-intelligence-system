/** Typed access to the backend through the server-side proxy. */
import type { components } from "./api-types";

export type S = components["schemas"];
export type InvoiceDetail = S["InvoiceDetail"];
export type Issue = S["IssueOut"];
export type SearchResponse = S["SearchResponse"];
export type GroupDetail = S["GroupDetail"];
export type RunWithEvents = S["RunWithEvents"];
export type Correction = S["CorrectionOut"];
export type UploadResponse = S["UploadResponse"];

// list endpoints return plain objects; their shapes are declared here
export interface InvoiceBrief {
  id: string;
  document_id: string;
  invoice_number: string | null;
  invoice_date: string | null;
  supplier_name: string | null;
  customer_name: string | null;
  total: string | null;
  currency: string | null;
  review_status: string;
  extraction_method: string;
  issue_count: number;
  group_id: string | null;
}
export interface DocumentBrief {
  id: string;
  filename: string;
  format: string;
  status: "queued" | "processing" | "completed" | "needs_review" | "failed";
  stage: string;
  progress_done: number;
  progress_total: number;
  page_count: number | null;
  uploaded_at: string;
  error_code: string | null;
  invoice_count: number;
}
export interface DocumentDetail extends DocumentBrief {
  size_bytes: number;
  sha256: string;
  error_message: string | null;
  exact_duplicate_of: string | null;
  pages: { page_number: number; kind: string; sheet_name: string | null; ocr_confidence: number | null }[];
  invoices: InvoiceBrief[];
  last_run: S["RunOut"] | null;
}
export interface Paged<T> { items: T[]; page: number; page_size: number; total: number }
export interface Stats {
  documents: Record<string, number>;
  failure_reasons: Record<string, number>;
  invoices: Record<string, number>;
  extraction_method: Record<string, number>;
  avg_ocr_ms_per_page: Record<string, number>;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

const BASE = "/api/proxy";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let body: { error?: { code?: string; message?: string; details?: unknown } } = {};
    try { body = await res.json(); } catch { /* not JSON */ }
    throw new ApiError(res.status, body.error?.code ?? "error", body.error?.message ?? res.statusText,
                       body.error?.details);
  }
  return res.json() as Promise<T>;
}

export const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const fileUrl = (docId: string) => `${BASE}/documents/${docId}/file`;
export const pageImageUrl = (docId: string, n: number) => `${BASE}/documents/${docId}/pages/${n}/image`;
export const exportUrl = (q: string) => `${BASE}/invoices/export${q}`;
