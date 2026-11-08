"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, Empty, ErrorBox, PageHeader } from "@/components/ui";
import { api, exportUrl, qs, type InvoiceBrief, type Paged } from "@/lib/api";
import { ISSUE_LABELS, METHOD_LABELS, date, money } from "@/lib/format";

function Queue() {
  const sp = useSearchParams();
  const router = useRouter();
  const review = sp.get("review_status") ?? "needs_review";
  const issue = sp.get("issue_code") ?? "";
  const [supplier, setSupplier] = useState(sp.get("supplier") ?? "");
  const [page, setPage] = useState(1);
  const params = { review_status: review, issue_code: issue, supplier: sp.get("supplier") ?? "" };
  const q = useQuery({
    queryKey: ["invoices", params, page],
    queryFn: () => api<Paged<InvoiceBrief>>(`/invoices${qs({ ...params, page, page_size: 25 })}`),
  });
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(sp.toString());
    p.set(k, v);
    setPage(1);
    router.replace(`/invoices?${p.toString()}`);
  };
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  return (
    <>
      <PageHeader title="Review queue" subtitle={q.data ? `${q.data.total} invoice${q.data.total === 1 ? "" : "s"}` : undefined}
        actions={<a className="btn-ghost" href={exportUrl(qs(params))}>Export CSV</a>} />
      <div className="mb-3 flex flex-wrap gap-2">
        <select className="input" value={review} onChange={(e) => set("review_status", e.target.value)} aria-label="Review status">
          <option value="needs_review">Needs review</option><option value="auto_approved">Auto-approved</option>
          <option value="reviewed">Reviewed</option><option value="">All</option>
        </select>
        <select className="input" value={issue} onChange={(e) => set("issue_code", e.target.value)} aria-label="Issue">
          <option value="">Any issue</option>
          {Object.entries(ISSUE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <form onSubmit={(e) => { e.preventDefault(); set("supplier", supplier); }}>
          <input className="input" placeholder="Supplier contains…" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
        </form>
      </div>
      <ErrorBox error={q.error} />
      {q.data?.items.length ? (
        <div className="card overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-line bg-paper/60"><tr>
              <th className="th">Invoice</th><th className="th">Supplier</th><th className="th">Customer</th><th className="th">Date</th>
              <th className="th text-right">Total</th><th className="th">Method</th><th className="th">Status</th><th className="th text-right">Issues</th></tr></thead>
            <tbody className="divide-y divide-line">
              {q.data.items.map((i) => (
                <tr key={i.id} className="hover:bg-paper/60">
                  <td className="td whitespace-nowrap"><Link className="font-medium text-navy-800 hover:underline" href={`/invoices/${i.id}`}>{i.invoice_number ?? "No number"}</Link></td>
                  <td className="td">{i.supplier_name ?? "–"}</td>
                  <td className="td">{i.customer_name ?? "–"}</td>
                  <td className="td whitespace-nowrap">{date(i.invoice_date)}</td>
                  <td className="td text-right whitespace-nowrap tabular-nums">{money(i.total, i.currency)}</td>
                  <td className="td text-muted">{METHOD_LABELS[i.extraction_method] ?? i.extraction_method}</td>
                  <td className="td"><Badge status={i.review_status} /></td>
                  <td className="td text-right tabular-nums">{i.issue_count}</td>
                </tr>))}
            </tbody>
          </table>
        </div>) : !q.isLoading && <Empty>Nothing in this view.</Empty>}
      {pages > 1 && (
        <div className="mt-3 flex items-center gap-2 text-sm">
          <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="text-muted">Page {page} of {pages}</span>
          <button className="btn-ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>)}
    </>
  );
}

export default function Page() {
  return <Suspense><Queue /></Suspense>;
}
