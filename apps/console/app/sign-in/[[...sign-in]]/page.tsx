import { Suspense } from "react";
import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="mm-auth-page">
      <Suspense>
        <SignIn />
      </Suspense>
    </main>
  );
}
