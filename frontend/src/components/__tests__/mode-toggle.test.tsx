import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ModeToggle } from "../mode-toggle";

describe("ModeToggle", () => {
  it("renders the toggle button", () => {
    render(<ModeToggle />);
    expect(screen.getByRole("button", { name: /toggle theme/i })).toBeInTheDocument();
  });
});
