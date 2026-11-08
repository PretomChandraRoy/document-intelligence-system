"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import DocumentsTable, { isActive } from "@/components/documents-table";
import { Empty, ErrorBox, PageHeader } from "@/components/ui";
import Upload from "@/components/upload";
import { api, json, qs, type DocumentBrief, type Paged } from "@/lib/api";

function Documents() {
  const sp = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const status = sp.get("status") ?? "";
  const format = sp.get("format") ?? "";
  const [page, setPage] = useState(1);
  const [retriedAt, setRetriedAt] = useState(0);
  const q = useQuery({
    queryKey: ["documents", status, format, page],
    queryFn: () => api<Paged<DocumentBrief>>(`/documents${qs({ status, format, page, page_size: 25 })}`),
    // keep refreshing while anything shown is processing, and briefly after a bulk
    // retry, because retried documents leave a "failed" view before they finish
    refetchInterval: (x) => (isActive(x.state.data?.items) || Date.now() - retriedAt < 30000 ? 2000 : false),
  });
  const retry = useMutation({
    mutationFn: () => api<{ queued: number }>("/documents/reprocess-failed", json("POST", {})),
    onSuccess: () => { setRetriedAt(Date.now()); qc.invalidateQueries({ queryKey: ["documents"] }); },
  });
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(sp.toString());
    if (v) p.set(k, v); else p.delete(k);
    setPage(1);
    router.replace(`/documents?${p.toString()}`);
  };
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;

  return (
    <>
      <PageHeader title="Documents" subtitle={q.data ? `${q.data.total} document${q.data.total === 1 ? "" : "s"}` : undefined}
        actions={<button className="btn-ghost" disabled={retry.isPending} onClick={() => retry.mutate()}>
          {retry.isPending ? "Resubmitting…" : "Reprocess all failed"}</button>} />
      {retry.data && <p className="mb-3 text-sm text-muted">{retry.data.queued} failed document(s) resubmitted.</p>}
      <div className="mb-4"><Upload /></div>
      <div className="mb-3 flex flex-wrap gap-2">
        <select className="input" value={status} onChange={(e) => set("status", e.target.value)} aria-label="Status">
          <option value="">All statuses</option><option value="queued">Queued</option>
          <option value="processing">Processing</option><option value="completed">Completed</option>
          <option value="needs_review">Needs review</option><option value="failed">Failed</option>
        </select>
        <select className="input" value={format} onChange={(e) => set("format", e.target.value)} aria-label="Format">
          <option value="">All formats</option>
          {["pdf", "jpg", "png", "tiff", "xlsx", "xls", "csv"].map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
        </select>
      </div>
      <ErrorBox error={q.error ?? retry.error} />
      {q.data?.items.length ? <DocumentsTable docs={q.data.items} /> : !q.isLoading && <Empty>No documents match.</Empty>}
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
  return <Suspense><Documents /></Suspense>;
}
