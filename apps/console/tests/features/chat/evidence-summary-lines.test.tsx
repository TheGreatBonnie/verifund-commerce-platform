import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceSummaryLines } from "@/features/chat/components/evidence-summary-lines";

describe("EvidenceSummaryLines", () => {
  it("renders evidence counts and verification status with reasons", () => {
    render(
      <EvidenceSummaryLines
        projection={
          {
            evidence: {
              required: ["serial", "provenance"],
              received: ["serial"],
            },
            verification: {
              status: "REVIEW_REQUIRED",
              reasons: ["battery below threshold"],
              override_allowed: true,
            },
          } as any
        }
      />,
    );

    expect(
      screen.getByText("1/2 required evidence items received"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Verification: REVIEW_REQUIRED · battery below threshold",
      ),
    ).toBeInTheDocument();
  });

  it("reports no evidence when the projection has none", () => {
    render(<EvidenceSummaryLines projection={{ evidence: null } as any} />);

    expect(screen.getByText("No evidence has been reported.")).toBeInTheDocument();
  });

  it("renders nothing without a projection", () => {
    const { container } = render(<EvidenceSummaryLines projection={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
