import { render, screen } from "@testing-library/react";
import { Status } from "./status";

test("renders label with tone class", () => {
  render(<Status tone="signal">Live</Status>);
  expect(screen.getByText("Live")).toHaveClass("is-signal");
});
