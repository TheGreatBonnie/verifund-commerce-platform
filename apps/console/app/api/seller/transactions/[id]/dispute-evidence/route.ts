import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { SellerApiError, uploadDisputeEvidence } from "@/lib/seller-api";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json(
      { error: { message: "Expected multipart form data" } },
      { status: 400 },
    );
  }
  try {
    const item = await uploadDisputeEvidence(id, formData);
    return NextResponse.json(item, { status: 201 });
  } catch (error) {
    if (error instanceof SellerApiError) {
      return NextResponse.json(
        { error: { message: error.message, code: error.code } },
        { status: error.status },
      );
    }
    return NextResponse.json(
      { error: { message: "Dispute evidence upload failed" } },
      { status: 500 },
    );
  }
}
