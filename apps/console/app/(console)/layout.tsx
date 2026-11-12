import { ConsoleLayout } from "@/components/layout/console-layout";
import { consoleSession } from "@/lib/console-session";

export const dynamic = "force-dynamic";

export default async function Layout({ children }: { children: React.ReactNode }) {
  const { userId, orgId } = await consoleSession();
  return (
    <ConsoleLayout userId={userId} orgId={orgId}>
      {children}
    </ConsoleLayout>
  );
}
