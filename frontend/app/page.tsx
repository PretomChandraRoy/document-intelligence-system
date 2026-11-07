"use client";
import { useQuery } from "@tanstack/react-query";
import DocumentsTable, { isActive } from "@/components/documents-table";
import { Empty, ErrorBox, PageHeader, Stat } from "@/components/ui";
import Upload from "@/components/upload";
import { api, type DocumentBrief, type Paged, type Stats } from "@/lib/api";

export default function Overview() {
  const docs = useQuery({
    queryKey: ["documents", "recent"],
    queryFn: () => api<Paged<DocumentBrief>>("/documents?page_size=8"),
    refetchInterval: (q) => (isActive(q.state.data?.items) ? 2000 : false),
  });
  const stats = useQuery({
    queryKey: ["stats"], queryFn: () => api<Stats>("/stats"),
    refetchInterval: isActive(docs.data?.items) ? 2000 : false,
  });
  const s = stats.data;
  const methods = s?.extraction_method ?? {};
  const totalInv = s?.invoices.total ?? 0;

  return (
    <>
      <PageHeader title="Overview" subtitle="Upload invoices, receipts, scans and spreadsheets. Each file is read, checked and indexed in the background." />
      <ErrorBox error={docs.error ?? stats.error} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Documents" value={s?.documents.total ?? "–"} href="/documents" />
        <Stat label="Invoices" value={totalInv || "–"} href="/invoices?review_status=" />
        <Stat label="Need review" value={s?.invoices.needs_review ?? "–"} href="/invoices" tone="text-warn" />
        <Stat label="Failed files" value={s?.documents.failed ?? "–"} href="/documents?status=failed" tone="text-err" />
        <Stat label="Read without model" value={totalInv ? `${Math.round(((methods.rules ?? 0) + (methods.spreadsheet ?? 0)) / totalInv * 100)}%` : "–"} />
      </div>
      <div className="mt-6"><Upload /></div>
      <h2 className="mt-8 mb-3 text-sm font-semibold text-navy-900">Recent documents</h2>
      {docs.data?.items.length ? <DocumentsTable docs={docs.data.items} /> :
        !docs.isLoading && <Empty>No documents yet. Upload some above.</Empty>}
    </>
  );
}
