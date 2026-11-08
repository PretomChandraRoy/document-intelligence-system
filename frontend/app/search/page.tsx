"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, Empty, ErrorBox, PageHeader } from "@/components/ui";
import { api, exportUrl, qs, type SearchResponse } from "@/lib/api";
import { date, money } from "@/lib/format";

const MODES = [
  { id: "hybrid", label: "Hybrid", hint: "Words and meaning combined" },
  { id: "keyword", label: "Keyword", hint: "Exact words, names and numbers" },
  { id: "semantic", label: "Semantic", hint: "Similar meaning, even with different words" },
];
const FILTERS = ["supplier", "customer", "currency", "date_from", "date_to", "min_total", "max_total", "review_status"] as const;

function Search() {
  const sp = useSearchParams();
  const router = useRouter();
  const read = () => Object.fromEntries([["q", sp.get("q") ?? ""], ["mode", sp.get("mode") ?? "hybrid"],
    ...FILTERS.map((f) => [f, sp.get(f) ?? ""])]) as Record<string, string>;
  const [form, setForm] = useState<Record<string, string>>(read);
  const applied = read();
  const active = applied.q || FILTERS.some((f) => applied[f]);

  const q = useQuery({
    queryKey: ["search", applied],
    queryFn: () => api<SearchResponse>(`/search${qs({ ...applied, limit: 50 })}`),
    enabled: !!active,
  });
  const submit = (next = form) => router.replace(`/search${qs(next)}`);
  const set = (k: string, v: string) => setForm({ ...form, [k]: v });
  const filterQs = qs(Object.fromEntries(FILTERS.map((f) => [f, applied[f]])));

  return (
    <>
      <PageHeader title="Search" subtitle="Find invoices by words, by meaning, or by filters."
        actions={active ? <a className="btn-ghost" href={exportUrl(filterQs)}>Export filtered CSV</a> : undefined} />
      <form className="card space-y-3 p-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="flex flex-wrap gap-2">
          <input className="input min-w-64 flex-1" placeholder='For example "printer toner", "home care for Mason", "INV-2026"'
            value={form.q} onChange={(e) => set("q", e.target.value)} aria-label="Search text" />
          <button className="btn-primary" type="submit">Search</button>
        </div>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Search mode">
          {MODES.map((m) => (
            <button key={m.id} type="button" role="radio" aria-checked={form.mode === m.id} title={m.hint}
              onClick={() => { const next: Record<string, string> = { ...form, mode: m.id }; setForm(next); if (next.q) submit(next); }}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${form.mode === m.id
                ? "border-navy-800 bg-navy-800 text-white" : "border-line bg-white text-ink hover:bg-paper"}`}>{m.label}</button>))}
          <span className="self-center text-xs text-muted">{MODES.find((m) => m.id === form.mode)?.hint}</span>
        </div>
        <div className="grid gap-2 sm:grid-cols-4">
          <input className="input" placeholder="Supplier contains" value={form.supplier} onChange={(e) => set("supplier", e.target.value)} />
          <input className="input" placeholder="Customer contains" value={form.customer} onChange={(e) => set("customer", e.target.value)} />
          <select className="input" value={form.currency} onChange={(e) => set("currency", e.target.value)} aria-label="Currency">
            <option value="">Any currency</option>{["BDT", "USD", "GBP", "EUR"].map((c) => <option key={c}>{c}</option>)}
          </select>
          <select className="input" value={form.review_status} onChange={(e) => set("review_status", e.target.value)} aria-label="Review status">
            <option value="">Any review status</option><option value="needs_review">Needs review</option>
            <option value="auto_approved">Auto-approved</option><option value="reviewed">Reviewed</option>
          </select>
          <label className="text-xs text-muted">From<input className="input mt-0.5 w-full" type="date" value={form.date_from} onChange={(e) => set("date_from", e.target.value)} /></label>
          <label className="text-xs text-muted">To<input className="input mt-0.5 w-full" type="date" value={form.date_to} onChange={(e) => set("date_to", e.target.value)} /></label>
          <label className="text-xs text-muted">Minimum total<input className="input mt-0.5 w-full" inputMode="decimal" value={form.min_total} onChange={(e) => set("min_total", e.target.value)} /></label>
          <label className="text-xs text-muted">Maximum total<input className="input mt-0.5 w-full" inputMode="decimal" value={form.max_total} onChange={(e) => set("max_total", e.target.value)} /></label>
        </div>
      </form>

      <div className="mt-5">
        <ErrorBox error={q.error} />
        {!active && <Empty>Type a search or set a filter.</Empty>}
        {q.data && (q.data.results.length ? (
          <>
            <p className="mb-2 text-sm text-muted">{q.data.results.length} result{q.data.results.length === 1 ? "" : "s"}
              {applied.q && <> for <strong className="text-ink">{applied.q}</strong> ({applied.mode})</>}</p>
            <ul className="space-y-2">
              {q.data.results.map((r) => (
                <li key={r.invoice_id} className="card px-4 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div>
                      <Link className="font-medium text-navy-800 hover:underline" href={`/invoices/${r.invoice_id}`}>
                        {r.supplier_name ?? "Unknown supplier"}</Link>
                      <span className="ml-2 text-sm text-muted">{r.invoice_number ?? "no number"} · {date(r.invoice_date)} · to {r.customer_name ?? "unknown"}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="tabular-nums font-medium">{money(r.total, r.currency)}</span>
                      <Badge status={r.review_status} />
                    </div>
                  </div>
                  {r.snippet && <p className="mt-1 text-sm text-muted [&_b]:bg-amber-100 [&_b]:font-medium [&_b]:text-ink"
                    dangerouslySetInnerHTML={{ __html: escapeExceptBold(r.snippet) }} />}
                  {applied.q && (
                    <p className="mt-1 text-xs text-muted">
                      {r.keyword_rank ? `keyword rank ${r.keyword_rank}` : "no keyword match"}
                      {applied.mode !== "keyword" && ` · ${r.semantic_rank ? `meaning rank ${r.semantic_rank}` : "no meaning match"}`}
                    </p>)}
                </li>))}
            </ul>
          </>) : <Empty>No invoices match.</Empty>)}
      </div>
    </>
  );
}

/** The snippet comes from document text, so escape everything except the <b> highlight tags we asked for. */
function escapeExceptBold(s: string): string {
  const esc = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/&lt;b&gt;/g, "<b>").replace(/&lt;\/b&gt;/g, "</b>");
}

export default function Page() {
  return <Suspense><Search /></Suspense>;
}
