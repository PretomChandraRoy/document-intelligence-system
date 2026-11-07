/**
 * Server-side proxy to the FastAPI backend.
 *
 * The browser calls /api/proxy/..., and this handler forwards the request to
 * the backend with the API key added. The key lives only in the Next.js
 * server's environment, so it never reaches the browser.
 */
import { NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
const KEY = process.env.DOCINTEL_API_KEY ?? "";
const PASS_HEADERS = ["content-type", "content-disposition", "cache-control"];

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (path.some((p) => p === ".." || p.includes("/"))) {
    return Response.json({ error: { code: "bad_path", message: "Invalid path" } }, { status: 400 });
  }
  const url = `${BACKEND}/api/v1/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers({ "X-API-Key": KEY });
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);

  const init: RequestInit & { duplex?: "half" } = { method: req.method, headers };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;   // streamed, so large uploads are not held in memory
    init.duplex = "half";
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    return Response.json({ error: { code: "backend_unreachable", message: "The API is not reachable" } },
                         { status: 502 });
  }
  const out = new Headers();
  for (const h of PASS_HEADERS) {
    const v = res.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(res.body, { status: res.status, headers: out });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const dynamic = "force-dynamic";
