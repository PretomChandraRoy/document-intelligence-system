"use client";
import Link from "next/link";
import type { ReactNode } from "react";

const STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: "Queued", cls: "bg-slate-100 text-slate-700" },
  processing: { label: "Processing", cls: "bg-blue-50 text-accent" },
  completed: { label: "Completed", cls: "bg-emerald-50 text-ok" },
  needs_review: { label: "Needs review", cls: "bg-amber-50 text-warn" },
  failed: { label: "Failed", cls: "bg-red-50 text-err" },
  auto_approved: { label: "Auto-approved", cls: "bg-emerald-50 text-ok" },
  reviewed: { label: "Reviewed", cls: "bg-emerald-50 text-ok" },
  consistent: { label: "Consistent", cls: "bg-emerald-50 text-ok" },
  mismatch: { label: "Mismatch", cls: "bg-red-50 text-err" },
};

export function Badge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, cls: "bg-slate-100 text-slate-700" };
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}>{s.label}</span>;
}

export function Severity({ level }: { level: string }) {
  const cls = level === "error" ? "bg-err" : level === "warning" ? "bg-warn" : "bg-slate-400";
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${cls}`} aria-label={level} />;
}

export function Progress({ done, total, status }: { done: number; total: number; status: string }) {
  const pct = total ? Math.round((done / total) * 100) : status === "failed" ? 100 : 0;
  const colour = status === "failed" ? "bg-err" : status === "needs_review" ? "bg-warn" :
    status === "completed" ? "bg-ok" : "bg-accent";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line" role="progressbar" aria-valuenow={pct}>
      <div className={`h-full ${colour} transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Confidence({ value }: { value: number | undefined }) {
  if (value === undefined) return null;
  const pct = Math.round(value * 100);
  const cls = value >= 0.9 ? "text-ok" : value >= 0.6 ? "text-warn" : "text-err";
  return <span className={`text-xs font-medium tabular-nums ${cls}`} title="Extraction confidence">{pct}%</span>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-navy-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="card px-6 py-10 text-center text-sm text-muted">{children}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="rounded-md border border-err/30 bg-red-50 px-3 py-2 text-sm text-err">{msg}</div>;
}

export function Stat({ label, value, href, tone }: { label: string; value: ReactNode; href?: string; tone?: string }) {
  const body = (
    <div className="card px-4 py-3 transition hover:border-navy-600/30">
      <div className="label">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? "text-navy-900"}`}>{value}</div>
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}
