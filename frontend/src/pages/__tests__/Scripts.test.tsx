import { render, screen, cleanup, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, it, expect, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Scripts } from "../Scripts";

// Hoisted so the vi.mock factory below can reference these safely
// (vi.mock factories run before module-level declarations).
const mocks = vi.hoisted(() => ({
  apiMock: vi.fn().mockResolvedValue([]),
  navMock: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: (...args: unknown[]) => mocks.apiMock(...args),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => mocks.navMock };
});

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

afterEach(() => {
  mocks.apiMock.mockReset();
  mocks.apiMock.mockResolvedValue([]);
  mocks.navMock.mockReset();
  cleanup();
});

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

  it("navigates to the script when a row cell is clicked", async () => {
    mocks.apiMock.mockResolvedValueOnce([
      { id: 7, name: "hello", language: "python", last_run: null, schedule: null },
    ]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Scripts />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const row = await screen.findByRole("row", { name: /hello/i });
    const user = userEvent.setup();
    await user.click(within(row).getByText("python"));
    expect(mocks.navMock).toHaveBeenCalledWith("/kindling/scripts/7");
  });

  it("does not navigate when the Run button is clicked", async () => {
    mocks.apiMock.mockResolvedValueOnce([
      { id: 7, name: "hello", language: "python", last_run: null, schedule: null },
    ]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Scripts />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const runBtn = await screen.findByRole("button", { name: /^run$/i });
    const user = userEvent.setup();
    await user.click(runBtn);
    expect(mocks.navMock).not.toHaveBeenCalled();
  });
});
