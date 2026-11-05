import { Suspense } from "react";
import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <main className="mm-auth-page">
      <Suspense>
        <SignUp />
      </Suspense>
    </main>
  );
}
