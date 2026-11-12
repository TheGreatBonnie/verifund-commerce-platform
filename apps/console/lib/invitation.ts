export function invitationRedirect(token: string) {
  const target = `/seller/onboarding?invitation=${encodeURIComponent(token)}`;
  return `/sign-in?redirect_url=${encodeURIComponent(target)}`;
}
