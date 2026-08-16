import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { SetupPage } from "../SetupPage";

vi.mock("../AuthProvider", () => ({
  useAuth: () => ({
    setup: vi.fn().mockResolvedValue(undefined),
    user: null,
    logout: vi.fn(),
    login: vi.fn(),
  }),
}));

describe("SetupPage", () => {
  it("renders form fields", () => {
    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>
    );
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create admin/i })).toBeInTheDocument();
  });
});
