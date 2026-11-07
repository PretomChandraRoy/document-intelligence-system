"use client";
import Link from "next/link";
import type { DocumentBrief } from "@/lib/api";
import { ERROR_LABELS, dateTime } from "@/lib/format";
import { Badge, Progress } from "./ui";

const STAGE: Record<string, string> = { ingest: "Reading file", ocr: "OCR", extract: "Extracting",
  post: "Validating", done: "Done" };

export default function DocumentsTable({ docs }: { docs: DocumentBrief[] }) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full">
        <thead className="border-b border-line bg-paper/60">
          <tr><th className="th">File</th><th className="th">Status</th><th className="th w-48">Progress</th>
            <th className="th text-right">Invoices</th><th className="th">Uploaded</th></tr>
        </thead>
        <tbody className="divide-y divide-line">
          {docs.map((d) => (
            <tr key={d.id} className="hover:bg-paper/60">
              <td className="td">
                <Link href={`/documents/${d.id}`} className="font-medium text-navy-800 hover:underline">{d.filename}</Link>
                <div className="text-xs text-muted uppercase">{d.format}{d.page_count ? ` · ${d.page_count} page${d.page_count > 1 ? "s" : ""}` : ""}</div>
              </td>
              <td className="td">
                <Badge status={d.status} />
                {d.status === "failed" && d.error_code &&
                  <div className="mt-0.5 text-xs text-err">{ERROR_LABELS[d.error_code] ?? d.error_code}</div>}
              </td>
              <td className="td">
                <Progress done={d.progress_done} total={d.progress_total} status={d.status} />
                <div className="mt-1 text-xs text-muted">
                  {d.status === "failed" ? `Stopped at: ${(STAGE[d.stage] ?? d.stage).toLowerCase()}` : STAGE[d.stage] ?? d.stage}
                  {d.progress_total ? ` · ${d.progress_done}/${d.progress_total} pages` : ""}
                </div>
              </td>
              <td className="td text-right tabular-nums">{d.invoice_count}</td>
              <td className="td text-muted">{dateTime(d.uploaded_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const isActive = (docs: DocumentBrief[] | undefined) =>
  !!docs?.some((d) => d.status === "queued" || d.status === "processing");
