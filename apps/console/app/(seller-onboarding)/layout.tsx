import { auth } from "@clerk/nextjs/server";

export const dynamic = "force-dynamic";

export default async function SellerOnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await auth.protect();
  return <>{children}</>;
}
