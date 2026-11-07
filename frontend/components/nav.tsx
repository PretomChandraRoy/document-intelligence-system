"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/documents", label: "Documents" },
  { href: "/invoices", label: "Review queue" },
  { href: "/groups", label: "Cross-checks" },
  { href: "/search", label: "Search" },
];

export default function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <aside className="flex w-56 shrink-0 flex-col bg-navy-900 text-slate-300 max-md:w-full max-md:flex-row max-md:items-center">
      <div className="px-5 py-5 max-md:py-3">
        <div className="text-sm font-semibold text-white">Document Intelligence</div>
        <div className="text-xs text-slate-400 max-md:hidden">Invoice processing</div>
      </div>
      <nav className="flex flex-col gap-0.5 px-2 max-md:flex-row max-md:overflow-x-auto">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href}
            className={`rounded-md px-3 py-2 text-sm whitespace-nowrap transition ${
              active(l.href) ? "bg-navy-700 text-white" : "hover:bg-navy-800 hover:text-white"}`}>
            {l.label}
          </Link>
        ))}
      </nav>
      <div className="mt-auto px-5 py-4 text-xs text-slate-500 max-md:hidden">
        Local model. No document data leaves this machine.
      </div>
    </aside>
  );
}
