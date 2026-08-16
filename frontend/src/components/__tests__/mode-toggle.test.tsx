import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import { ModeToggle } from "../mode-toggle";

describe("ModeToggle", () => {
  it("renders the toggle button", () => {
    render(<ModeToggle />);
    expect(screen.getByRole("button", { name: /toggle theme/i })).toBeInTheDocument();
  });

  it("opens the dropdown and shows light, dark, and system menu items", async () => {
    const user = userEvent.setup();
    render(<ModeToggle />);
    const trigger = screen.getAllByRole("button", { name: /toggle theme/i })[0];
    await user.click(trigger);

    expect(screen.getByRole("menuitem", { name: /light/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /dark/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /system/i })).toBeInTheDocument();
  });
});
