import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Dashboard } from "../Dashboard";
import { useIsMobile } from "@/hooks/use-mobile";
import { api } from "@/api/client";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: vi.fn(),
}));

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: 1, email: "u@example.com" },
    login: vi.fn(),
    logout: vi.fn(),
    setup: vi.fn(),
  }),
}));

const RUN = {
  id: 1,
  script_name: "demo",
  status: "success",
  started_at: new Date().toISOString(),
  duration: "1.2s",
};

function mockApi() {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "/scripts") return [];
    if (path === "/schedules") return [];
    if (path === "/runs") return [RUN];
    return [];
  });
}

function renderDashboard() {
  mockApi();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Dashboard", () => {
  beforeEach(() => {
    vi.mocked(useIsMobile).mockReturnValue(false);
  });

  it("renders stat cards", async () => {
    renderDashboard();
    expect(await screen.findByText("Total scripts")).toBeInTheDocument();
    expect(await screen.findByText("Active schedules")).toBeInTheDocument();
  });

  it("renders table on desktop", async () => {
    vi.mocked(useIsMobile).mockReturnValue(false);
    renderDashboard();
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(await screen.findByText("demo")).toBeInTheDocument();
  });

  it("renders card list on mobile", async () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    renderDashboard();
    expect(await screen.findByText("demo")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
