import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { Settings } from "../Settings";

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: 1, email: "admin@example.com", role: "admin" },
    login: vi.fn(),
    logout: vi.fn(),
    setup: vi.fn(),
  }),
}));

vi.mock("@/api/admin", () => ({
  listUsers: vi.fn().mockResolvedValue([
    { id: 1, email: "a@example.com", role: "admin" },
    { id: 2, email: "b@example.com", role: "editor" },
  ]),
  listAudit: vi.fn().mockResolvedValue([
    {
      id: 1,
      user_id: 1,
      action: "user.create",
      resource_type: "user",
      resource_id: 2,
      at: "2026-01-01T00:00:00Z",
      meta_json: "{}",
    },
  ]),
  createInvite: vi.fn().mockResolvedValue({ token: "abc", expires_at: "2026-01-08" }),
  deleteUser: vi.fn().mockResolvedValue(undefined),
  changeRole: vi.fn().mockResolvedValue(undefined),
}));

function renderWithProviders() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Settings", () => {
  it("renders Profile, Security, System sections", async () => {
    renderWithProviders();
    expect(screen.getByText(/profile/i)).toBeInTheDocument();
    expect(screen.getByText(/security/i)).toBeInTheDocument();
    expect(screen.getAllByText(/system/i).length).toBeGreaterThan(0);
  });

  it("renders admin sections (Users, Invite, Audit) for admin user", async () => {
    renderWithProviders();
    const usersHeadings = await screen.findAllByText(/^users$/i);
    expect(usersHeadings.length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^invite$/i).length).toBeGreaterThan(0);
    const auditHeadings = await screen.findAllByText(/audit log/i);
    expect(auditHeadings.length).toBeGreaterThan(0);
  });
});