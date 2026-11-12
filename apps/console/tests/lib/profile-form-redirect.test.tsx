import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const push = vi.fn();
const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

const saveProfileAction = vi.fn(async () => ({ ok: true, data: {} }));
vi.mock("@/app/(seller-onboarding)/seller/onboarding/actions", () => ({
  saveProfileAction: (...args: unknown[]) => saveProfileAction(...args),
}));

import { ProfileForm } from "@/components/seller-agent/ProfileForm";

describe("ProfileForm next step (backend contract)", () => {
  it("navigates to agent_setup after profile save, not verification", async () => {
    render(<ProfileForm initialDisplayName="Acme" />);
    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: "Acme" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(push).toHaveBeenCalledWith("/seller/onboarding/agent_setup");
  });
});
