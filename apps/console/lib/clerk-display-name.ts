type ClerkUserLike = {
  fullName?: string | null;
  firstName?: string | null;
  lastName?: string | null;
  username?: string | null;
  id?: string | null;
  primaryEmailAddress?: { emailAddress?: string | null } | null;
};

function clean(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function clerkDisplayName(
  user: ClerkUserLike | null | undefined,
): string | undefined {
  return (
    clean(user?.fullName) ??
    clean([user?.firstName, user?.lastName].filter(Boolean).join(" ")) ??
    clean(user?.username) ??
    clean(user?.primaryEmailAddress?.emailAddress) ??
    clean(user?.id)
  );
}

export function approverDisplayName(
  user: ClerkUserLike | null | undefined,
): string {
  return clerkDisplayName(user) ?? "Demo Buyer";
}
