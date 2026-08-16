import { render, screen, cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { Schedules } from "../Schedules";

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

describe("Schedules", () => {
  it("renders header, new schedule button, and table columns", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Schedules />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByRole("heading", { name: /schedules/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new schedule/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /cron/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /script/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /enabled/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /last run/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /next run/i })).toBeInTheDocument();
  });
});
