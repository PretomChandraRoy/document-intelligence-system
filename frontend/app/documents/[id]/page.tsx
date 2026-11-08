"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { Badge, Confidence, ErrorBox, PageHeader, Progress } from "@/components/ui";
import { api, fileUrl, json, type DocumentDetail, type RunWithEvents } from "@/lib/api";
import { ERROR_LABELS, bytes, dateTime, money } from "@/lib/format";

export default function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const qc = useQueryClient();
  const [stage, setStage] = useState("ingest");
  const active = (d?: DocumentDetail) => d?.status === "queued" || d?.status === "processing";
  const doc = useQuery({
    queryKey: ["documents", id],
    queryFn: () => api<DocumentDetail>(`/documents/${id}`),
    refetchInterval: (q) => (active(q.state.data) ? 2000 : false),
  });
  const history = useQuery({
    queryKey: ["documents", id, "history", doc.data?.status],
    queryFn: () => api<RunWithEvents[]>(`/documents/${id}/history`),
    enabled: !!doc.data,
  });
  const reprocess = useMutation({
    mutationFn: () => api(`/documents/${id}/reprocess`, json("POST", { from_stage: stage })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
  const d = doc.data;
  if (!d) return <ErrorBox error={doc.error} />;

  return (
    <>
      <PageHeader title={d.filename}
        subtitle={<>{d.format.toUpperCase()} · {bytes(d.size_bytes)}
          {d.page_count ? ` · ${d.page_count} ${["xlsx", "xls", "csv"].includes(d.format) ? "sheet" : "page"}${d.page_count > 1 ? "s" : ""}` : ""}</>}
        actions={<>
          <a className="btn-ghost" href={fileUrl(d.id)} target="_blank" rel="noreferrer">Open original</a>
          <select className="input" value={stage} onChange={(e) => setStage(e.target.value)} aria-label="Reprocess from">
            <option value="ingest">From the start</option><option value="extract">From extraction</option>
            <option value="post">Validation only</option>
          </select>
          <button className="btn-primary" disabled={active(d) || reprocess.isPending} onClick={() => reprocess.mutate()}>Reprocess</button>
        </>} />
      <ErrorBox error={reprocess.error} />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card p-4 lg:col-span-2">
          <div className="flex items-center gap-3"><Badge status={d.status} />
            <span className="text-sm text-muted">Stage: {d.stage}</span></div>
          <div className="mt-3"><Progress done={d.progress_done} total={d.progress_total} status={d.status} /></div>
          {d.status === "failed" && (
            <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm break-words text-err">
              <strong>{ERROR_LABELS[d.error_code ?? ""] ?? d.error_code}.</strong> {d.error_message}
            </div>)}
          {d.exact_duplicate_of && (
            <div className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-warn">
              This exact file was uploaded before. <Link className="underline" href={`/documents/${d.exact_duplicate_of}`}>View the earlier upload</Link>.
            </div>)}

          <h2 className="mt-5 mb-2 text-sm font-semibold">Invoices found ({d.invoices.length})</h2>
          {d.invoices.length ? (
            <table className="w-full">
              <thead className="border-b border-line"><tr><th className="th">Number</th><th className="th">Supplier</th>
                <th className="th text-right">Total</th><th className="th">Review</th><th className="th text-right">Issues</th></tr></thead>
              <tbody className="divide-y divide-line">
                {d.invoices.map((i) => (
                  <tr key={i.id} className="hover:bg-paper/60">
                    <td className="td"><Link className="font-medium text-navy-800 hover:underline" href={`/invoices/${i.id}`}>{i.invoice_number ?? "No number"}</Link></td>
                    <td className="td">{i.supplier_name ?? "–"}</td>
                    <td className="td text-right tabular-nums">{money(i.total, i.currency)}</td>
                    <td className="td"><Badge status={i.review_status} /></td>
                    <td className="td text-right tabular-nums">{i.issue_count}</td>
                  </tr>))}
              </tbody>
            </table>) : <p className="text-sm text-muted">None yet.</p>}
        </div>

        <div className="card p-4">
          <h2 className="mb-2 text-sm font-semibold">Pages</h2>
          {d.pages.length === 0 && <p className="text-sm text-muted">No pages were read.</p>}
          <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
            {d.pages.map((p) => (
              <li key={p.page_number} className="flex justify-between">
                <span>{p.sheet_name ? `Sheet "${p.sheet_name}"` : `Page ${p.page_number}`}</span>
                <span className="text-muted">{p.kind}{p.ocr_confidence !== null &&
                  <> · OCR <Confidence value={p.ocr_confidence / 100} /></>}</span>
              </li>))}
          </ul>
        </div>
      </div>

      <h2 className="mt-6 mb-2 text-sm font-semibold">Processing history</h2>
      <div className="space-y-3">
        {history.data?.map((r) => (
          <div key={r.id} className="card p-4">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="font-medium">Attempt {r.attempt}</span><span className="text-muted">{r.trigger}</span>
              <Badge status={r.status === "succeeded" ? "completed" : r.status === "running" ? "processing" : "failed"} />
              <span className="text-muted">{dateTime(r.started_at)}</span>
              <span className="text-muted tabular-nums">
                {["ingest", "ocr", "extract", "post"].filter((k) => k in r.stage_timings_ms)
                  .map((k) => `${k} ${(Number(r.stage_timings_ms[k]) / 1000).toFixed(1)} s`).join(" · ")}
              </span>
            </div>
            <ul className="mt-2 space-y-0.5 text-sm">
              {r.events.map((e, i) => (
                <li key={i} className={`break-words ${e.level === "error" ? "text-err" : e.level === "warning" ? "text-warn" : "text-muted"}`}>
                  <span className="mr-2 font-mono text-xs">{e.stage}</span>{e.message}
                </li>))}
            </ul>
          </div>))}
      </div>
    </>
  );
}
