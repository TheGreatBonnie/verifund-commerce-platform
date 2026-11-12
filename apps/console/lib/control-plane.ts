import { auth } from "@clerk/nextjs/server";

const CONTROL_PLANE =
  process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";

export async function controlPlaneForUser(path: string, init: RequestInit = {}) {
  const { getToken, orgId } = await auth();
  const token = await (getToken as (opts: { organizationId?: string }) => Promise<string | null>)({
    organizationId: orgId ?? undefined,
  });
  if (!token) throw new Error("not signed in");
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  return fetch(`${CONTROL_PLANE}${path}`, {
    ...init,
    cache: "no-store",
    headers,
  });
}

export async function controlPlaneAsPlatform(
  path: string,
  init: RequestInit = {},
  timeoutMs = 10_000,
) {
  const token = process.env.VERIFUND_OPS_TOKEN ?? "dev-verifund-ops";
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  return fetch(`${CONTROL_PLANE}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: AbortSignal.timeout(timeoutMs),
  });
}
