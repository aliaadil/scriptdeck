import { render, screen, cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { RunView } from "../RunView";

vi.mock("@/lib/api", () => ({
  api: vi.fn().mockResolvedValue({ id: "abc", script_name: "test", status: "success", output: "" }),
}));

afterEach(() => cleanup());

describe("RunView", () => {
  it("renders tabs", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/runs/abc"]}>
          <Routes>
            <Route path="/runs/:id" element={<RunView />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByRole("tab", { name: /output/i })).toBeInTheDocument();
  });
});
