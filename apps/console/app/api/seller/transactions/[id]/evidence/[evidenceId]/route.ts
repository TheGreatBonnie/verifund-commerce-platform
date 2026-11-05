import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { SellerApiError, sellerRequest } from "@/lib/seller-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; evidenceId: string }> },
) {
  await auth.protect();
  const { id, evidenceId } = await params;
  try {
    const upstream = await sellerRequest(
      `/seller/transactions/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}`,
      {},
      id,
    );
    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(text, {
        status: upstream.status,
        headers: {
          "content-type":
            upstream.headers.get("content-type") ?? "application/json",
        },
      });
    }
    const bytes = await upstream.arrayBuffer();
    return new Response(bytes, {
      status: 200,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "application/octet-stream",
        "content-disposition":
          upstream.headers.get("content-disposition") ?? "inline",
      },
    });
  } catch (error) {
    if (error instanceof SellerApiError) {
      return NextResponse.json(
        { error: { message: error.message, code: error.code } },
        { status: error.status },
      );
    }
    return NextResponse.json(
      { error: { message: "Evidence download failed" } },
      { status: 500 },
    );
  }
}
