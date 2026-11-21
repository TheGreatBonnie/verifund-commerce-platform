import { consoleSession } from "@/lib/console-session";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function adminAccess(): Promise<boolean> {
  await consoleSession(); // auth.protect() — fail closed for signed-out users
  try {
    const response = await controlPlaneForUser("/v1/me");
    if (!response.ok) return false;
    const body = (await response.json()) as { is_platform_admin?: unknown };
    return body.is_platform_admin === true;
  } catch {
    return false;
  }
}
