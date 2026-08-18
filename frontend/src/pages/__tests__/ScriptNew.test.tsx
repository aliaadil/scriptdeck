import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { it, expect, vi } from "vitest";
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

it("shows three cards and creates a script on pick", async () => {
  mockCreate.mockResolvedValue({ id: 7, name: "Untitled script", language: "python", entrypoint: "main.py", source_path: "scripts/7", description: null });
  renderPage();
  fireEvent.click(screen.getByTestId("card-python"));
  await waitFor(() => expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({ language: "python", template: "python" })));
  await waitFor(() => expect(mockNav).toHaveBeenCalledWith("/kindling/scripts/7"));
});