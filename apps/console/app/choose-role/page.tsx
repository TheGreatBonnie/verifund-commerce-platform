import { auth } from "@clerk/nextjs/server";
import { ChooseRoleClient } from "./choose-role-client";

export const dynamic = "force-dynamic";

export default async function ChooseRolePage() {
  await auth.protect();
  return <ChooseRoleClient />;
}
