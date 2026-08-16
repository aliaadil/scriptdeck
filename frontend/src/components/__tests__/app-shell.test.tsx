import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { AppShell } from "../AppShell";

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { email: "admin@example.com", role: "admin" },
    logout: vi.fn(),
  }),
}));

describe("AppShell", () => {
  it("renders nav links", () => {
    render(
      <MemoryRouter>
        <AppShell>
          <div>child</div>
        </AppShell>
      </MemoryRouter>
    );
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Scripts")).toBeInTheDocument();
    expect(screen.getByText("Schedules")).toBeInTheDocument();
    expect(screen.getByText("Runs")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });
});
