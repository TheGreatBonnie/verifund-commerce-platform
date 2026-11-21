import { auth, clerkClient } from "@clerk/nextjs/server";
import { adminAccess } from "@/lib/admin-access";

export const dynamic = "force-dynamic";

export async function GET() {
  await auth.protect();
  if (!(await adminAccess())) {
    return Response.json({ error: "forbidden" }, { status: 403 });
  }
  const client = await clerkClient();
  const users = await client.users.getUserList({ limit: 100 });
  return Response.json(
    {
      users: users.data.map((u) => ({
        id: u.id,
        email:
          u.emailAddresses.find((e) => e.id === u.primaryEmailAddressId)
            ?.emailAddress ?? null,
        role: (u.publicMetadata?.role as string) ?? null,
      })),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
