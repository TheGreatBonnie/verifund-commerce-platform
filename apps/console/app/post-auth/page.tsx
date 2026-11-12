import { auth, currentUser } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { promoteUserRole, type UserRole } from "@/lib/user-role";
import { SellerActivator } from "./seller-activator";

export const dynamic = "force-dynamic";

function isRole(value: unknown): value is UserRole {
  return value === "buyer" || value === "seller";
}

export default async function PostAuthPage() {
  let userId: string;
  try {
    const res = await auth.protect();
    if (!res?.userId) redirect("/sign-in");
    userId = res.userId;
  } catch (err) {
    console.error("post-auth: unauthenticated", err);
    redirect("/sign-in");
    return null as never;
  }

  let role: UserRole | undefined;
  try {
    const user = await currentUser();
    role = isRole(user?.publicMetadata?.role)
      ? (user?.publicMetadata?.role as UserRole)
      : undefined;

    if (!role && isRole(user?.unsafeMetadata?.role)) {
      const hinted = user?.unsafeMetadata?.role as UserRole;
      await promoteUserRole(userId, hinted);
      role = hinted;
    }
  } catch (err) {
    console.error("post-auth: failed to resolve role", err);
  }

  if (!role) redirect("/choose-role");

  if (role === "seller") {
    // Org activation must happen client-side so Clerk can set the new org as
    // active in the session (Backend-API-created orgs aren't active). See
    // ./seller-activator.tsx.
    return <SellerActivator />;
  }

  redirect("/");
}
