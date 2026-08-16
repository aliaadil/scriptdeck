import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { Dashboard } from "../Dashboard";

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ scripts: [], runs: [] }),
  },
}));

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: 1, email: "u@example.com" },
    login: vi.fn(),
    logout: vi.fn(),
    setup: vi.fn(),
  }),
}));

describe("Dashboard", () => {
  it("renders stat cards", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText("Total scripts")).toBeInTheDocument();
    expect(await screen.findByText("Active schedules")).toBeInTheDocument();
  });
});
