import { auth } from "@clerk/nextjs/server";
import { ConsoleLayout } from "@/components/layout/console-layout";

export const dynamic = "force-dynamic";

export default async function PublicLayout({ children }: { children: React.ReactNode }) {
  const { userId, orgId } = await auth();
  return (
    <ConsoleLayout userId={userId ?? undefined} orgId={orgId ?? null}>
      {children}
    </ConsoleLayout>
  );
}
