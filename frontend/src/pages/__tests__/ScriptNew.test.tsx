import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ScriptNew } from "../ScriptNew";

const mockCreate = vi.fn();
const mockNav = vi.fn();
vi.mock("@/api/scripts", () => ({ createScript: (...a: unknown[]) => mockCreate(...a) }));
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<any>("react-router-dom")),
  useNavigate: () => mockNav,
}));
vi.mock("@/components/ui/sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: 1, email: "u@example.com" },
    login: vi.fn(),
    logout: vi.fn(),
    setup: vi.fn(),
  }),
}));

const renderPage = () => {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ScriptNew />
      </MemoryRouter>
    </QueryClientProvider>
  );
};

describe("ScriptNew", () => {
  beforeEach(() => {
    mockCreate.mockReset();
    mockNav.mockReset();
  });

  it("shows three cards and creates a script on pick", async () => {
    mockCreate.mockResolvedValue({
      id: 7,
      name: "morning-report",
      language: "python",
      entrypoint: "main.py",
      source_path: "scripts/7",
      description: null,
    });
    renderPage();
    // Type a real name first — the placeholder default is now blocked.
    fireEvent.change(screen.getByTestId("new-name-input"), {
      target: { value: "morning-report" },
    });
    fireEvent.click(screen.getByTestId("card-python"));
    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({ language: "python", template: "python", name: "morning-report" }),
      ),
    );
    await waitFor(() => expect(mockNav).toHaveBeenCalledWith("/kindling/scripts/7"));
  });

  it("blocks create actions while the name is the Untitled-script placeholder", async () => {
    renderPage();
    // Default pre-fills with the placeholder; prompt is visible.
    expect(screen.getByTestId("new-name-prompt")).toBeInTheDocument();
    expect(screen.getByTestId("card-python")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByTestId("blank-editor")).toBeDisabled();

    // Card click should not invoke create even though it bubbles.
    fireEvent.click(screen.getByTestId("card-python"));
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it("unblocks actions once a real name is typed", async () => {
    renderPage();
    fireEvent.change(screen.getByTestId("new-name-input"), {
      target: { value: "  data-sync  " },
    });
    expect(screen.queryByTestId("new-name-prompt")).not.toBeInTheDocument();
    expect(screen.getByTestId("card-python")).toHaveAttribute("aria-disabled", "false");
    expect(screen.getByTestId("blank-editor")).not.toBeDisabled();
  });

  it("treats the placeholder case-insensitively as invalid", async () => {
    renderPage();
    fireEvent.change(screen.getByTestId("new-name-input"), {
      target: { value: "  UNTITLED SCRIPT  " },
    });
    expect(screen.getByTestId("new-name-prompt")).toBeInTheDocument();
  });
});