"use client";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { UploadResponse } from "@/lib/api";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv";
const MAX_FILES = 20;

/** Drag-and-drop upload. Sends files in batches of 20 (the API's per-request limit). */
export default function Upload() {
  const input = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(0);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send(files: File[]) {
    if (!files.length) return;
    setBusy(true); setError(null); setResult(null); setSent(0);
    const all: UploadResponse = { accepted: [], rejected: [] };
    try {
      for (let i = 0; i < files.length; i += MAX_FILES) {
        const form = new FormData();
        files.slice(i, i + MAX_FILES).forEach((f) => form.append("files", f));
        const res = await fetch("/api/proxy/documents", { method: "POST", body: form });
        const body = await res.json();
        if (!res.ok) throw new Error(body?.error?.message ?? `Upload failed (${res.status})`);
        all.accepted.push(...body.accepted);
        all.rejected.push(...body.rejected);
        setSent(Math.min(i + MAX_FILES, files.length));
      }
      setResult(all);
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); send(Array.from(e.dataTransfer.files)); }}
        onClick={() => input.current?.click()}
        className={`card flex cursor-pointer flex-col items-center justify-center border-2 border-dashed px-6 py-8 text-center transition ${
          over ? "border-accent bg-blue-50/50" : "border-line hover:border-navy-600/40"}`}>
        <div className="text-sm font-medium text-navy-900">
          {busy ? `Uploading… ${sent} sent` : "Drop documents here or click to choose"}
        </div>
        <div className="mt-1 text-xs text-muted">PDF, JPG, PNG, TIFF, XLSX, XLS or CSV. Up to 200 MB each.</div>
        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden"
               onChange={(e) => send(Array.from(e.target.files ?? []))} />
      </div>
      {error && <div className="mt-2 text-sm text-err">{error}</div>}
      {result && (
        <div className="mt-2 text-sm">
          <span className="text-ok">{result.accepted.length} accepted</span>
          {result.accepted.some((a) => a.exact_duplicate_of) && (
            <span className="ml-2 text-warn">
              ({result.accepted.filter((a) => a.exact_duplicate_of).length} identical to an earlier upload)
            </span>)}
          {result.rejected.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-err">
              {result.rejected.map((r) => <li key={r.filename}>{r.filename}: {r.message}</li>)}
            </ul>)}
        </div>
      )}
    </div>
  );
}
