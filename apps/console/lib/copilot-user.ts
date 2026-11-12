import { auth, currentUser } from "@clerk/nextjs/server";

type ClerkProfile = {
  fullName?: string | null;
  firstName?: string | null;
  lastName?: string | null;
  username?: string | null;
  primaryEmailAddress?: {
    emailAddress?: string | null;
  } | null;
};

function clean(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function copilotDisplayName(user: ClerkProfile | null | undefined): string | undefined {
  return (
    clean(user?.fullName) ??
    clean([user?.firstName, user?.lastName].filter(Boolean).join(" ")) ??
    clean(user?.username) ??
    clean(user?.primaryEmailAddress?.emailAddress)
  );
}

export async function identifyCopilotUser() {
  const { userId } = await auth.protect();

  try {
    const user = await currentUser();
    return {
      id: userId,
      name: copilotDisplayName(user) ?? userId,
    };
  } catch {
    // The Intelligence profile name is useful, not an authorization boundary.
    // Preserve a non-empty fallback instead of blocking the agent run.
    return {
      id: userId,
      name: userId,
    };
  }
}
