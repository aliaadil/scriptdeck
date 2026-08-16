import { render, screen, cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { Scripts } from "../Scripts";

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

vi.mock("@/components/ui/sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

afterEach(() => cleanup());

describe("Scripts", () => {
  it("renders page header, new script button, and table columns", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Scripts />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByRole("heading", { name: /scripts/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new script/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /name/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /language/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /schedule/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /last run/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /actions/i })).toBeInTheDocument();
  });
});
