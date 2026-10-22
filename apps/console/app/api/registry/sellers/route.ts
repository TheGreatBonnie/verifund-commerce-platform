export async function GET() {
  const registry = process.env.REGISTRY_URL ?? "http://127.0.0.1:9105";
  try {
    const response = await fetch(`${registry}/v1/sellers`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return Response.json(
      { error: "Registry is offline" },
      { status: 503 },
    );
  }
}
