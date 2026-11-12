import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

export default async function SellerIndexPage() {
  await auth.protect();
  redirect("/seller/dashboard");
}
