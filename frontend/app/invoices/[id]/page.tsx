"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";
import { useReviewer } from "@/components/reviewer";
import { Badge, Confidence, ErrorBox, PageHeader, Severity } from "@/components/ui";
import { api, fileUrl, json, pageImageUrl, type Correction, type InvoiceDetail } from "@/lib/api";
import { FIELD_LABELS, ISSUE_LABELS, dateTime, money } from "@/lib/format";

const FIELDS = ["invoice_number", "invoice_date", "supplier_name", "customer_name",
  "subtotal", "tax", "total", "currency"] as const;
type Field = (typeof FIELDS)[number];
type Line = { description: string; quantity: string; unit_price: string; amount: string };

const toLines = (inv: InvoiceDetail): Line[] => inv.line_items.map((l) => ({
  description: l.description ?? "", quantity: l.quantity ?? "", unit_price: l.unit_price ?? "", amount: l.amount ?? "",
}));

export default function InvoicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const qc = useQueryClient();
  const [reviewer, setReviewer] = useReviewer();
  const inv = useQuery({ queryKey: ["invoice", id], queryFn: () => api<InvoiceDetail>(`/invoices/${id}`) });
  const history = useQuery({
    queryKey: ["invoice", id, "corrections", inv.data?.reviewed_at],
    queryFn: () => api<Correction[]>(`/invoices/${id}/corrections`),
  });

  const [form, setForm] = useState<Record<Field, string>>({} as Record<Field, string>);
  const [lines, setLines] = useState<Line[]>([]);
  const [note, setNote] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!inv.data) return;
    const f = {} as Record<Field, string>;
    for (const k of FIELDS) f[k] = (inv.data[k] as string | null) ?? "";
    setForm(f);
    setLines(toLines(inv.data));
    setPage(inv.data.page_start ?? 1);
  }, [inv.data]);

  const changed = useMemo(() => {
    if (!inv.data) return {} as Partial<Record<Field, string | null>>;
    const out: Partial<Record<Field, string | null>> = {};
    for (const k of FIELDS) {
      const before = (inv.data[k] as string | null) ?? "";
      if (form[k] !== undefined && form[k] !== before) out[k] = form[k] === "" ? null : form[k];
    }
    return out;
  }, [form, inv.data]);
  const linesChanged = inv.data ? JSON.stringify(lines) !== JSON.stringify(toLines(inv.data)) : false;
  const dirty = Object.keys(changed).length > 0 || linesChanged;

  const done = (data: InvoiceDetail) => {
    qc.setQueryData(["invoice", id], data);
    qc.invalidateQueries({ queryKey: ["invoices"] });
    qc.invalidateQueries({ queryKey: ["documents"] });
    setNote("");
  };
  const save = useMutation({
    mutationFn: () => api<InvoiceDetail>(`/invoices/${id}`, json("PATCH", {
      corrected_by: reviewer, fields: changed, note: note || null,
      line_items: linesChanged ? lines.map((l) => ({
        description: l.description || null, quantity: l.quantity || null,
        unit_price: l.unit_price || null, amount: l.amount || null })) : null,
    })),
    onSuccess: done,
  });
  const review = useMutation({
    mutationFn: (decision: "approve" | "accept_with_issues") =>
      api<InvoiceDetail>(`/invoices/${id}/review`, json("POST", { reviewed_by: reviewer, decision, note: note || null })),
    onSuccess: done,
  });

  const d = inv.data;
  if (!d) return <ErrorBox error={inv.error} />;
  const open = d.issues.filter((i) => !i.resolved);
  const errors = open.filter((i) => i.severity === "error");
  const isSheet = d.sheet_name !== null || (d.page_start === null && d.page_end === null);
  const pages = d.page_start && d.page_end ? Array.from({ length: d.page_end - d.page_start + 1 }, (_, k) => d.page_start! + k) : [];
  const issueFor = (f: string) => open.filter((i) => i.field === f || i.field?.startsWith(`${f}[`));
  const sumLines = lines.reduce((s, l) => s + (Number(l.amount) || 0), 0);

  return (
    <>
      <PageHeader title={d.invoice_number ? `Invoice ${d.invoice_number}` : "Invoice without a number"}
        subtitle={<>From <Link className="underline" href={`/documents/${d.document_id}`}>{d.document_filename}</Link>
          {d.page_start && <> · page {d.page_start}{d.page_end !== d.page_start && `–${d.page_end}`}</>}
          {" · "}read by <strong>{d.extraction_method}</strong></>}
        actions={<Badge status={d.review_status} />} />

      <div className="grid gap-4 xl:grid-cols-2">
        {/* left: the original, so values can be checked against it */}
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-3 py-2 text-sm">
            <span className="label">Original</span>
            <div className="flex items-center gap-2">
              {pages.length > 1 && pages.map((p) => (
                <button key={p} onClick={() => setPage(p)}
                  className={`rounded px-2 py-0.5 text-xs ${p === page ? "bg-navy-800 text-white" : "bg-paper"}`}>{p}</button>))}
              <a className="text-accent hover:underline" href={fileUrl(d.document_id)} target="_blank" rel="noreferrer">Open file</a>
            </div>
          </div>
          {isSheet ? (
            <div className="p-6 text-sm text-muted">Spreadsheet{d.sheet_name ? `, sheet "${d.sheet_name}"` : ""}. Open the file to compare.</div>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={pageImageUrl(d.document_id, page)} alt={`Page ${page}`} className="w-full bg-white" />
          )}
        </div>

        {/* right: extracted fields, editable */}
        <div className="space-y-4">
          {open.length > 0 && (
            <div className="card p-4">
              <h2 className="mb-2 text-sm font-semibold">Issues ({open.length})</h2>
              <ul className="space-y-1.5">
                {open.map((i) => (
                  <li key={i.id} className="flex gap-2 text-sm">
                    <Severity level={i.severity} />
                    <div><span className="font-medium">{ISSUE_LABELS[i.code] ?? i.code}.</span> {i.message}
                      {i.code === "duplicate" && d.group && <> <Link className="text-accent underline" href={`/groups/${d.group.id}`}>Compare</Link></>}
                    </div>
                  </li>))}
              </ul>
            </div>)}

          <div className="card p-4">
            <h2 className="mb-3 text-sm font-semibold">Extracted fields</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {FIELDS.map((f) => (
                <label key={f} className="block">
                  <span className="flex items-center justify-between">
                    <span className="label">{FIELD_LABELS[f]}</span>
                    <Confidence value={d.field_confidence[f] as number | undefined} />
                  </span>
                  <input className={`input mt-1 w-full ${issueFor(f).length ? "border-warn" : ""} ${changed[f] !== undefined ? "bg-blue-50" : ""}`}
                    type={f === "invoice_date" ? "date" : "text"} inputMode={["subtotal", "tax", "total"].includes(f) ? "decimal" : undefined}
                    value={form[f] ?? ""} placeholder="Not on document"
                    onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
                  {typeof d.evidence[f] === "string" && <span className="mt-0.5 block truncate font-mono text-[11px] text-muted" title={String(d.evidence[f])}>“{String(d.evidence[f])}”</span>}
                </label>))}
            </div>
          </div>

          <div className="card p-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Line items ({lines.length})</h2>
              <Confidence value={d.field_confidence.line_items as number | undefined} />
            </div>
            <div className="max-h-80 overflow-auto">
              <table className="w-full">
                <thead><tr><th className="th">Description</th><th className="th w-20 text-right">Qty</th>
                  <th className="th w-28 text-right">Unit price</th><th className="th w-28 text-right">Amount</th><th className="w-6" /></tr></thead>
                <tbody>
                  {lines.map((l, i) => (
                    <tr key={i} className={issueFor(`line_items[${i}]`).length ? "bg-amber-50" : ""}>
                      {(["description", "quantity", "unit_price", "amount"] as const).map((k) => (
                        <td key={k} className="px-1 py-0.5">
                          <input className={`input w-full py-1 ${k !== "description" ? "text-right tabular-nums" : ""}`} value={l[k]}
                            onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} />
                        </td>))}
                      <td><button className="px-1 text-muted hover:text-err" title="Remove line" onClick={() => setLines(lines.filter((_, j) => j !== i))}>×</button></td>
                    </tr>))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex items-center justify-between text-sm">
              <button className="text-accent hover:underline" onClick={() => setLines([...lines, { description: "", quantity: "", unit_price: "", amount: "" }])}>Add line</button>
              <span className="text-muted">Lines add up to <strong className="tabular-nums text-ink">{money(sumLines.toFixed(2), d.currency)}</strong></span>
            </div>
          </div>

          <div className="card p-4">
            <div className="grid gap-2 sm:grid-cols-[1fr_2fr]">
              <input className="input" placeholder="Your name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} aria-label="Reviewer name" />
              <input className="input" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note" />
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button className="btn-primary" disabled={!dirty || !reviewer || save.isPending} onClick={() => save.mutate()}>
                {save.isPending ? "Saving…" : "Save corrections"}</button>
              <button className="btn-ghost" disabled={dirty || !reviewer || errors.length > 0 || review.isPending} onClick={() => review.mutate("approve")}
                title={errors.length ? "Correct the errors first, or accept them" : undefined}>Approve</button>
              {errors.length > 0 && (
                <button className="btn-danger" disabled={dirty || !reviewer || review.isPending} onClick={() => review.mutate("accept_with_issues")}>
                  Accept with {errors.length} error{errors.length > 1 ? "s" : ""}</button>)}
            </div>
            {!reviewer && <p className="mt-2 text-xs text-muted">Enter your name; it is recorded with every change.</p>}
            <ErrorBox error={save.error ?? review.error} />
          </div>

          {(history.data?.length ?? 0) > 0 && (
            <div className="card p-4">
              <h2 className="mb-2 text-sm font-semibold">Correction history</h2>
              <ul className="space-y-1 text-sm">
                {history.data!.map((c, i) => (
                  <li key={i}><span className="text-muted">{dateTime(c.created_at)} · {c.corrected_by}:</span>{" "}
                    <strong>{FIELD_LABELS[c.field_path] ?? c.field_path}</strong>{" "}
                    {c.field_path === "line_items" ? "edited" : <>{c.old_value ?? "empty"} → {c.new_value ?? "empty"}</>}
                    {c.note && <span className="text-muted"> ({c.note})</span>}</li>))}
              </ul>
            </div>)}
        </div>
      </div>
    </>
  );
}
