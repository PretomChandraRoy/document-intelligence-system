"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Empty, ErrorBox, PageHeader } from "@/components/ui";
import { api, qs, type GroupDetail, type Paged } from "@/lib/api";
import { FIELD_LABELS } from "@/lib/format";

const METHOD: Record<string, string> = { key: "Same supplier and number", fuzzy: "Similar supplier, same date and total",
  manual: "Linked by a reviewer" };

export default function Groups() {
  const [status, setStatus] = useState("");
  const q = useQuery({
    queryKey: ["groups", status],
    queryFn: () => api<Paged<GroupDetail>>(`/groups${qs({ status, page_size: 100 })}`),
  });
  const mism = q.data?.items.filter((g) => g.status === "mismatch").length ?? 0;
  return (
    <>
      <PageHeader title="Cross-checks"
        subtitle="The same invoice found in more than one document: duplicates submitted twice, and PDFs checked against other PDFs or spreadsheet records."
        actions={<select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All</option><option value="mismatch">Mismatches</option><option value="consistent">Consistent duplicates</option>
        </select>} />
      {q.data && !status && (
        <p className="mb-3 text-sm text-muted">{q.data.total} group{q.data.total === 1 ? "" : "s"}; <span className="text-err">{mism} with differences</span>.</p>)}
      <ErrorBox error={q.error} />
      {q.data?.items.length ? (
        <div className="card overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-line bg-paper/60"><tr>
              <th className="th">Invoice</th><th className="th">Documents</th><th className="th">Result</th>
              <th className="th">Differences</th><th className="th">Matched by</th></tr></thead>
            <tbody className="divide-y divide-line">
              {q.data.items.map((g) => {
                const number = g.comparison.find((r) => r.field === "invoice_number")?.values.find((v) => v);
                return (
                  <tr key={g.id} className="hover:bg-paper/60">
                    <td className="td whitespace-nowrap"><Link className="font-medium text-navy-800 hover:underline" href={`/groups/${g.id}`}>{number ?? "No number"}</Link></td>
                    <td className="td">{g.members.map((m) => (
                      <span key={m.invoice_id} className="mr-1.5 inline-flex items-center gap-1 rounded bg-paper px-1.5 py-0.5 text-xs">
                        <span className="font-semibold uppercase text-muted">{m.format}</span>{m.document}</span>))}</td>
                    <td className="td"><Badge status={g.status} /></td>
                    <td className="td text-sm">{g.mismatched_fields.length
                      ? <span className="text-err">{g.mismatched_fields.map((f) => FIELD_LABELS[f] ?? f).join(", ")}</span>
                      : <span className="text-muted">None</span>}</td>
                    <td className="td text-muted">{METHOD[g.match_method] ?? g.match_method}</td>
                  </tr>);
              })}
            </tbody>
          </table>
        </div>) : !q.isLoading && <Empty>No invoice appears in more than one document yet.</Empty>}
    </>
  );
}
