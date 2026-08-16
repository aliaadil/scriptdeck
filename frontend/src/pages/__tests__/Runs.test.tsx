import { render, screen, cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { Runs } from "../Runs";

vi.mock("@/api/client", () => ({
  api: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: 1, email: "u@example.com" },
    login: vi.fn(),
    logout: vi.fn(),
    setup: vi.fn(),
  }),
}));

afterEach(() => cleanup());

describe("Runs", () => {
  it("renders header", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Runs />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByRole("heading", { name: /runs/i })).toBeInTheDocument();
  });
});