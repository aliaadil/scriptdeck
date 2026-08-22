import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, afterEach } from "vitest";
import { RunView } from "../RunView";

const run = vi.hoisted(() => ({
  id: 42,
  script_id: 7,
  schedule_id: null,
  trigger_kind: "manual",
  started_at: "2026-01-01T00:00:00Z",
  ended_at: "2026-01-01T00:00:03Z",
  exit_code: 0,
  status: "success",
}));

vi.mock("@/api/runs", () => ({
  getRun: vi.fn().mockResolvedValue(run),
  cancelRun: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api/client", () => ({
  api: vi.fn().mockResolvedValue({ content: "hello from log\n" }),
}));

vi.mock("@/hooks/useLiveLogs", () => ({
  useLiveLogs: () => ({ events: [], ended: true }),
}));

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: 1, email: "admin@example.com", role: "admin" } }),
}));

afterEach(() => cleanup());

function renderRunView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/runs/42"]}>
        <Routes>
          <Route path="/runs/:id" element={<RunView />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RunView", () => {
  it("renders tabs", async () => {
    renderRunView();
    expect(await screen.findByRole("tab", { name: /output/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /config/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /metadata/i })).toBeInTheDocument();
  });

  it("renders run header, status and derived duration", async () => {
    renderRunView();
    expect(await screen.findByText("Run #42")).toBeInTheDocument();
    expect(await screen.findByText("success")).toBeInTheDocument();
    expect(await screen.findByText("3.0s")).toBeInTheDocument();
  });

  it("renders fallback log content from JSON wrapper", async () => {
    renderRunView();
    expect(await screen.findByText(/hello from log/)).toBeInTheDocument();
  });
});
