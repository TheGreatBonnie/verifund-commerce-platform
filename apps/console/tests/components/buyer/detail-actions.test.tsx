import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BuyerConfirmDialog } from "@/components/buyer/shared/buyer-confirm-dialog";
import { ActionBar } from "@/components/buyer/fulfillment/action-bar";
import { DisputePanel } from "@/components/buyer/fulfillment/dispute-panel";
import { mapActionError } from "@/lib/buyer-action-errors";

const api = vi.hoisted(() => ({ openBuyerDispute: vi.fn() }));
vi.mock("@/lib/buyer-transaction-api", () => ({
  openBuyerDispute: api.openBuyerDispute,
}));

describe("BuyerConfirmDialog", () => {
  it("requires an explicit confirm and supports cancel", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <BuyerConfirmDialog
        title="Accept offer"
        body="This accepts the agreed terms."
        confirmLabel="Accept offer"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Accept offer" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Accept offer" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

describe("ActionBar", () => {
  it("explains why actions are disabled and never enables without authority", () => {
    render(
      <ActionBar
        allowedActions={[]}
        blockers={[{ code: "awaiting_evidence", message: "Evidence is still required." }]}
        nextAction="awaiting_evidence"
        onAccept={vi.fn()}
        onConfirmDelivery={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Confirm delivery" })).toBeDisabled();
    expect(screen.getByText(/evidence is still required/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toHaveAttribute(
      "title",
      expect.stringContaining("Evidence is still required"),
    );
  });

  it("confirms acceptance, runs the action and announces success", async () => {
    const onAccept = vi.fn().mockResolvedValue(undefined);
    render(
      <ActionBar
        allowedActions={["accept"]}
        onAccept={onAccept}
        onConfirmDelivery={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(screen.getByRole("dialog", { name: /accept offer/i })).toBeInTheDocument();
    expect(onAccept).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm acceptance" }));
    await waitFor(() => expect(onAccept).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("status")).toHaveTextContent(/accepted/i);
  });

  it("maps a stale-state conflict to actionable feedback", async () => {
    const conflict: any = new Error("transaction state changed");
    conflict.status = 409;
    render(
      <ActionBar
        allowedActions={["delivery_confirmed"]}
        onAccept={vi.fn()}
        onConfirmDelivery={vi.fn().mockRejectedValue(conflict)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Confirm delivery" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm delivery action" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/no longer available/i);
  });
});

describe("DisputePanel", () => {
  it("confirms before opening a dispute and announces success", async () => {
    api.openBuyerDispute.mockResolvedValue({});
    const onChanged = vi.fn().mockResolvedValue(undefined);
    render(
      <DisputePanel
        transactionId="tx_1"
        allowedActions={["dispute"]}
        onChanged={onChanged}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText("Describe the issue"), {
      target: { value: "Goods did not arrive" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open dispute" }));
    expect(screen.getByRole("dialog", { name: /open dispute/i })).toBeInTheDocument();
    expect(api.openBuyerDispute).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm dispute" }));
    await waitFor(() => expect(api.openBuyerDispute).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("status")).toHaveTextContent(/dispute opened/i);
  });
});

describe("mapActionError", () => {
  it("maps authoritative status codes to readable messages", () => {
    const conflict: any = new Error("state changed");
    conflict.status = 409;
    expect(mapActionError(conflict)).toMatch(/no longer available/i);

    const invalid: any = new Error("bad input");
    invalid.status = 422;
    expect(mapActionError(invalid)).toMatch(/rejected/i);
  });
});
