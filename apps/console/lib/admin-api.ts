import { auth } from "@clerk/nextjs/server";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function adminJson<T>(path: string): Promise<T> {
  await auth.protect(); // literal guard — every admin page includes this transitively
  const response = await controlPlaneForUser(path);
  if (response.status === 403) throw new Error("forbidden");
  if (!response.ok) throw new Error(`admin API ${response.status}`);
  return (await response.json()) as T;
}
