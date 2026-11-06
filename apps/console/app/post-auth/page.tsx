import { auth, currentUser, clerkClient } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { promoteUserRole, type UserRole } from "@/lib/user-role";

export const dynamic = "force-dynamic";

function isRole(value: unknown): value is UserRole {
  return value === "buyer" || value === "seller";
}

export default async function PostAuthPage() {
  const { userId } = await auth.protect();
  if (!userId) redirect("/sign-in");

  const user = await currentUser();
  let role: UserRole | undefined = isRole(user?.publicMetadata?.role)
    ? (user?.publicMetadata?.role as UserRole)
    : undefined;

  // Promote a one-time hint from sign-up (unsafeMetadata) into the
  // authoritative publicMetadata store, then stop trusting the hint.
  if (!role && isRole(user?.unsafeMetadata?.role)) {
    const hinted = user?.unsafeMetadata?.role as UserRole;
    await promoteUserRole(userId, hinted);
    role = hinted;
  }

  if (!role) redirect("/choose-role");

  if (role === "seller") {
    const client = await clerkClient();
    const memberships = await client.users.getOrganizationMembershipList({ userId });
    if ((memberships.data ?? []).length === 0) {
      const email = user?.primaryEmailAddress?.emailAddress;
      const name = user?.firstName
        ? `${user.firstName}'s business`
        : email
          ? `${email.split("@")[0]}'s business`
          : "My business";
      await client.organizations.createOrganization({ name, createdBy: userId });
    }
    redirect("/seller/onboarding");
  }

  redirect("/");
}
