"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { Badge, ErrorBox, PageHeader } from "@/components/ui";
import { api, type GroupDetail } from "@/lib/api";
import { FIELD_LABELS, money } from "@/lib/format";

const MONEY = new Set(["subtotal", "tax", "total"]);

export default function GroupPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const q = useQuery({ queryKey: ["groups", id], queryFn: () => api<GroupDetail>(`/groups/${id}`) });
  const g = q.data;
  if (!g) return <ErrorBox error={q.error} />;
  const fmt = (field: string, v: string | null) => (v === null ? <span className="text-muted">Not on document</span>
    : MONEY.has(field) ? money(v) : v);

  return (
    <>
      <PageHeader title="Cross-check"
        subtitle={g.status === "mismatch"
          ? `These documents describe the same invoice but disagree on ${g.mismatched_fields.length} field${g.mismatched_fields.length > 1 ? "s" : ""}. One of them is wrong; check against the source.`
          : "These documents describe the same invoice and agree on every field: most likely a duplicate submission."}
        actions={<Badge status={g.status} />} />
      <div className="card overflow-x-auto">
        <table className="w-full">
          <thead className="border-b border-line bg-paper/60">
            <tr><th className="th w-40">Field</th>
              {g.members.map((m) => (
                <th key={m.invoice_id} className="th normal-case">
                  <Link className="text-navy-800 hover:underline" href={`/invoices/${m.invoice_id}`}>{m.document}</Link>
                  <span className="ml-1.5 text-[11px] uppercase">{m.format}</span>
                </th>))}
              <th className="th w-24">Match</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {g.comparison.map((r) => (
              <tr key={r.field} className={r.match ? "" : "bg-red-50/60"}>
                <td className="td font-medium">{FIELD_LABELS[r.field] ?? r.field}</td>
                {r.values.map((v, i) => (
                  <td key={i} className={`td tabular-nums ${r.match ? "" : "font-medium text-err"}`}>{fmt(r.field, v)}</td>))}
                <td className="td">{r.match ? <span className="text-ok">Same</span> : <span className="font-medium text-err">Different</span>}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-muted">
        Open either invoice to correct it. After a correction the documents are compared again automatically.
      </p>
    </>
  );
}
