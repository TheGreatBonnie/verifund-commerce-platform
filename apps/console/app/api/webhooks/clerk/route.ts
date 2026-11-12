import { controlPlaneAsPlatform } from "@/lib/control-plane";

export async function POST(request: Request) {
  const body = await request.text();
  const headers = new Headers({ "content-type": "application/json" });
  for (const name of ["svix-id", "svix-timestamp", "svix-signature"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const response = await controlPlaneAsPlatform("/v1/webhooks/clerk", {
    method: "POST",
    headers,
    body,
  });
  return new Response(await response.text(), { status: response.status });
}
