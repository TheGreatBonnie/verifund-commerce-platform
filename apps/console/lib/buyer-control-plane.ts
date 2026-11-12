import { auth } from "@clerk/nextjs/server";

const CONTROL_PLANE =
  process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";

type BuyerProxyOptions = {
  timeoutMs?: number;
};

export async function controlPlaneBuyer(
  path: string,
  init: RequestInit = {},
  opts: BuyerProxyOptions = {},
) {
  const { getToken, orgId } = await auth();
  const token = await (getToken as (o: { organizationId?: string }) => Promise<string | null>)({
    organizationId: orgId ?? undefined,
  });
  if (!token) {
    return new Response(JSON.stringify({ error: { message: "not signed in" } }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }

  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  if (orgId) headers.set("x-verifund-org-id", String(orgId));

  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (isFormData) headers.delete("content-type");

  return fetch(`${CONTROL_PLANE}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: opts.timeoutMs ? AbortSignal.timeout(opts.timeoutMs) : init.signal,
  });
}

export async function passthroughUpstream(res: Response) {
  const body = await res.arrayBuffer();
  const headers = new Headers();
  const ct = res.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  const cd = res.headers.get("content-disposition");
  if (cd) headers.set("content-disposition", cd);
  return new Response(body, { status: res.status, headers });
}
