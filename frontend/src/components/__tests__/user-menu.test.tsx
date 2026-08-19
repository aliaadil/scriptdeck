import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { UserMenu } from "../user-menu";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: vi.fn(),
}));

import { useIsMobile } from "@/hooks/use-mobile";

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { email: "admin@example.com", role: "admin" },
    logout: vi.fn(),
  }),
}));

describe("UserMenu", () => {
  it("renders the user email", () => {
    vi.mocked(useIsMobile).mockReturnValue(false);
    render(
      <MemoryRouter>
        <UserMenu />
      </MemoryRouter>,
    );
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
  });

  it("shows Settings link for admins inside the menu on mobile", async () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <UserMenu />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: /admin@example.com/i }));
    const settings = screen.getByRole("menuitem", { name: /settings/i });
    expect(settings).toBeInTheDocument();
    expect(settings.tagName).toBe("A");
    expect(settings).toHaveAttribute("href", "/kindling/settings");
  });

  it("does not show Settings link for admins on desktop", async () => {
    vi.mocked(useIsMobile).mockReturnValue(false);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <UserMenu />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: /admin@example.com/i }));
    expect(screen.queryByRole("menuitem", { name: /^settings/i })).toBeNull();
  });
});
