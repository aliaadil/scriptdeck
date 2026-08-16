import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { LoginPage } from "../LoginPage";

vi.mock("../AuthProvider", () => ({
  useAuth: () => ({
    login: vi.fn().mockResolvedValue(undefined),
    user: null,
    logout: vi.fn(),
    setup: vi.fn(),
  }),
}));

describe("LoginPage", () => {
  it("renders form fields", () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });
});
