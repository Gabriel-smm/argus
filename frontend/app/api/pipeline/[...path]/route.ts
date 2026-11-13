import { type NextRequest, NextResponse } from "next/server";

import { isAllowedRequestContext } from "@/lib/request-context";

// Both uploaded files travel in one JSON body.
const MAX_BODY_BYTES = 5 * 1024 * 1024;

function errorResponse(error: string, status: number) {
  return NextResponse.json({ error, field: null }, { status });
}

async function handleRequest(req: NextRequest, method: string) {
  if (!isAllowedRequestContext(req)) {
    return errorResponse("Cross-origin requests are not allowed.", 403);
  }

  const apiUrl = process.env.PIPELINE_API_URL?.trim() || "http://127.0.0.1:8000";
  const path = req.nextUrl.pathname.replace(/^\/?api\/pipeline\//, "");
  // Pass the query on (GET /scene?name=drone), minus the route's own catch-all parameter.
  const search = new URLSearchParams(req.nextUrl.search);
  search.delete("path");
  search.delete("nxtPpath");
  const query = search.toString() ? `?${search.toString()}` : "";

  const options: RequestInit = { method, signal: req.signal };
  if (method === "POST") {
    const body = await req.text();
    if (Buffer.byteLength(body) > MAX_BODY_BYTES) {
      return errorResponse("The files are too large. Together they must stay under 5 MB.", 413);
    }
    options.body = body;
    options.headers = { "content-type": "application/json" };
  }

  let res: Response;
  try {
    res = await fetch(`${apiUrl}/${path}${query}`, options);
  } catch {
    return errorResponse("The Laya service is not running. Start it with `npm run dev`.", 503);
  }

  return new NextResponse(res.body, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}

export const GET = (req: NextRequest) => handleRequest(req, "GET");
export const POST = (req: NextRequest) => handleRequest(req, "POST");
export const DELETE = (req: NextRequest) => handleRequest(req, "DELETE");
