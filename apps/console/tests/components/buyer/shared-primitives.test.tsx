import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BuyerStatusPill } from "@/components/buyer/shared/buyer-status-pill";
import { BuyerOverviewCards } from "@/components/buyer/shared/buyer-overview-cards";
import {
  BuyerErrorState,
  BuyerPageSkeleton,
  BuyerSuccessMessage,
} from "@/components/buyer/shared/buyer-page-states";
import { RawDataDisclosure } from "@/components/buyer/shared/raw-data-disclosure";
import { ChatHandoffLink } from "@/components/buyer/shared/chat-handoff-link";

describe("BuyerStatusPill", () => {
  it("shows a text-first status with a tone derived from the value", () => {
    render(<BuyerStatusPill value="REVIEW_REQUIRED" />);
    expect(screen.getByText("REVIEW_REQUIRED")).toHaveClass(
      "mm-buyer-status-pill",
      "is-amber",
    );
  });

  it("accepts an explicit label and tone", () => {
    render(<BuyerStatusPill value="PAID" label="Paid in full" tone="signal" />);
    expect(screen.getByText("Paid in full")).toHaveClass("is-signal");
  });
});

describe("BuyerOverviewCards", () => {
  it("renders labelised aggregate counts", () => {
    render(
      <BuyerOverviewCards aggregates={{ awaiting_payment: 2, total: 5 }} />,
    );
    expect(screen.getByText("Awaiting Payment")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
  });

  it("explains missing aggregates", () => {
    render(<BuyerOverviewCards emptyMessage="Counts unavailable." />);
    expect(screen.getByText("Counts unavailable.")).toBeInTheDocument();
  });
});

describe("Buyer page states", () => {
  it("marks loading skeletons as busy", () => {
    render(<BuyerPageSkeleton label="Loading transactions" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText(/loading transactions/i)).toBeInTheDocument();
  });

  it("offers a retry for failed loads", () => {
    const onRetry = vi.fn();
    render(<BuyerErrorState message="Network failed" onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("distinguishes a missing record from a failed load", () => {
    render(<BuyerErrorState notFound message="Transaction not found" backHref="/transactions" />);
    expect(screen.getByText(/does not exist/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to transactions/i })).toHaveAttribute(
      "href",
      "/transactions",
    );
  });

  it("announces successful actions politely", () => {
    render(<BuyerSuccessMessage>Delivery confirmed</BuyerSuccessMessage>);
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });
});

describe("RawDataDisclosure", () => {
  it("hides raw JSON behind a keyboard-accessible disclosure", () => {
    render(<RawDataDisclosure label="View raw payment" value={{ id: "pay_1" }} />);
    expect(screen.getByText("View raw payment")).toBeInTheDocument();
    const pre = screen.getByLabelText("Raw payment");
    expect(pre).toHaveAttribute("tabindex", "0");
    expect(pre).toHaveTextContent('"id": "pay_1"');
  });
});

describe("ChatHandoffLink", () => {
  it("links to the chat with the transaction and intent", () => {
    render(
      <ChatHandoffLink transactionId="tx 1" intent="release">
        Review &amp; release in chat
      </ChatHandoffLink>,
    );
    const link = screen.getByRole("link", { name: /review release in chat for tx 1/i });
    expect(link).toHaveAttribute("aria-label", "Review release in chat for tx 1");
    expect(link).toHaveAttribute("href", "/chat?transaction_id=tx+1&intent=release");
  });
});
