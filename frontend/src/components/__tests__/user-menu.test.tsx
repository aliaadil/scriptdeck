import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { UserMenu } from "../user-menu";

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { email: "admin@example.com", role: "admin" },
    logout: vi.fn(),
  }),
}));

describe("UserMenu", () => {
  it("renders the user email", () => {
    render(
      <MemoryRouter>
        <UserMenu />
      </MemoryRouter>,
    );
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
  });
});