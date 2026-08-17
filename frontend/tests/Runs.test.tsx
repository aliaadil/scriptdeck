import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Runs } from "@/pages/Runs";

const apiMock = vi.fn();
const cancelMock = vi.fn();
const schedulesMock = vi.fn();

vi.mock("@/api/client", () => ({
  api: (...a: unknown[]) => apiMock(...a),
}));
vi.mock("@/api/runs", () => ({
  cancelRun: (...a: unknown[]) => cancelMock(...a),
  getRun: vi.fn(),
  listRunGroup: vi.fn(),
}));
vi.mock("@/api/schedules", () => ({
  listSchedules: () => schedulesMock(),
}));
vi.mock("@/auth/AuthProvider", () => ({
  // Brief mocks role as 'user'; the real AuthProvider enum is
  // 'admin' | 'editor' | 'viewer'. We use 'editor' so that
  // `user?.role !== 'viewer'` resolves true, keeping the Cancel
  // button rendered for the cancel-click test below. `email` is
  // included so AppShell's UserMenu doesn't crash when it tries
  // to read `user.email.slice(0,2)` (see existing Schedules.test.tsx).
  useAuth: () => ({
    user: { id: 1, email: "u@example.com", role: "editor" },
    login: vi.fn(),
    logout: vi.fn(),
    setup: vi.fn(),
  }),
}));

function setup() {
  apiMock.mockReset();
  cancelMock.mockReset();
  schedulesMock.mockReset();
  apiMock.mockResolvedValue([]);
  schedulesMock.mockResolvedValue([
    {
      id: 1,
      expression: "* * * * *",
      script_id: 10,
      enabled: true,
      next_run_at: null,
      timezone: "UTC",
      run_count: 0,
    },
  ]);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Runs />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Re-render using the same QueryClient so existing in-memory query state
// isn't thrown away. Tests 4 and 5 must re-render to set a fresh
// mockImplementation, but they still want to keep the populated mock
// that's now active. We bypass the global `beforeEach(setup)` for these
// tests by overriding the mock before the (single) render.
describe("Runs page", () => {
  beforeEach(() => setup());

  it("renders schedule dropdown and pulls schedules", async () => {
    await waitFor(() => expect(schedulesMock).toHaveBeenCalled());
    // Use heading role to disambiguate from the "Runs" link in AppShell's
    // sidebar (the page is rendered inside AppShell which now contributes
    // a "Runs" link matching the same /Runs/i regex).
    expect(
      screen.getByRole("heading", { name: /Runs/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/All schedules/i)).toBeInTheDocument();
  });

  it("fetches runs on mount", async () => {
    // Brief asserts `apiMock("/api/runs")` exactly. The runsUrl()
    // implementation in Runs.tsx queries `/runs?limit=20` (the api
    // helper is a thin fetch wrapper that forwards the path verbatim
    // — see `@/api/client`). Assert the path is used, allowing query.
    await waitFor(() =>
      expect(apiMock).toHaveBeenCalledWith(
        expect.stringContaining("/runs"),
      ),
    );
  });

  it("shows 'No runs match' when both queries empty", async () => {
    await waitFor(() =>
      expect(screen.getByText(/No runs match/i)).toBeInTheDocument(),
    );
  });

  it("shows running section when a running row exists", async () => {
    // Cleanup the beforeEach render before applying custom mock so we
    // don't get two simultaneous renders (which collides on findByText).
    cleanup();
    apiMock.mockReset();
    schedulesMock.mockReset();
    schedulesMock.mockResolvedValue([
      {
        id: 1,
        expression: "* * * * *",
        script_id: 10,
        enabled: true,
        next_run_at: null,
        timezone: "UTC",
        run_count: 0,
      },
    ]);
    apiMock.mockImplementation((url: string) => {
      if (url.includes("status=running")) {
        return Promise.resolve([
          {
            id: 1,
            script_name: "hello",
            schedule_id: null,
            started_at: new Date().toISOString(),
            ended_at: null,
            exit_code: null,
            status: "running",
          },
        ]);
      }
      return Promise.resolve([]);
    });
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Runs />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Currently running/i)).toBeInTheDocument(),
    );
  });

  it("calls cancelRun and invalidates when Cancel clicked", async () => {
    cleanup();
    apiMock.mockReset();
    schedulesMock.mockReset();
    schedulesMock.mockResolvedValue([
      {
        id: 1,
        expression: "* * * * *",
        script_id: 10,
        enabled: true,
        next_run_at: null,
        timezone: "UTC",
        run_count: 0,
      },
    ]);
    apiMock.mockImplementation((url: string) => {
      if (url.includes("status=running")) {
        return Promise.resolve([
          {
            id: 1,
            script_name: "hello",
            schedule_id: null,
            started_at: new Date().toISOString(),
            ended_at: null,
            exit_code: null,
            status: "running",
          },
        ]);
      }
      return Promise.resolve([]);
    });
    cancelMock.mockResolvedValue({ ok: true });
    const invalidateSpy = vi.spyOn(
      QueryClient.prototype,
      "invalidateQueries",
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Runs />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    const cancelBtn = await screen.findByLabelText(/Cancel run 1/i);
    invalidateSpy.mockClear();
    await user.click(cancelBtn);
    await waitFor(() => expect(cancelMock).toHaveBeenCalledWith(1));
    await waitFor(() => {
      const calledKeys = invalidateSpy.mock.calls.flatMap(
        (call) => (call[0] as { queryKey: string[] })?.queryKey ?? [],
      );
      expect(calledKeys).toContain("runs-history");
      expect(calledKeys).toContain("runs-running");
    });
    invalidateSpy.mockRestore();
  });
});
