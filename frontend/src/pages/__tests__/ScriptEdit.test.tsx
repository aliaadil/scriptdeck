import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ScriptEdit } from "../ScriptEdit";

const apiMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: (...args: unknown[]) => apiMock(...args),
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

vi.mock("@monaco-editor/react", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange?: (v: string | undefined) => void;
  }) => (
    <textarea
      data-testid="monaco-mock"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

function renderNew() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/scripts/new"]}>
        <Routes>
          <Route path="/scripts/:id" element={<ScriptEdit />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderExisting(sourceContent: string = "print('hi')") {
  apiMock.mockResolvedValueOnce({
    id: "1",
    name: "test",
    language: "python",
    description: "d",
  });
  apiMock.mockResolvedValueOnce({ content: sourceContent });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/scripts/1"]}>
        <Routes>
          <Route path="/scripts/:id" element={<ScriptEdit />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ScriptEdit", () => {
  beforeEach(() => {
    apiMock.mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : (input as URL).toString();
        if (url.endsWith("/source")) {
          return Promise.resolve(new Response("print('hi')", { status: 200 }));
        }
        return Promise.resolve(new Response("", { status: 404 }));
      }) as unknown as typeof fetch,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders tabs", async () => {
    renderExisting();
    expect(await screen.findByRole("tab", { name: /editor/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /config/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /logs/i })).toBeInTheDocument();
  });

  it("loads source via api JSON wrapper", async () => {
    renderExisting("print('hi')\n");
    // The source text should appear in the Monaco editor (mocked textarea).
    const editor = (await screen.findAllByTestId("monaco-mock"))[0];
    await waitFor(() =>
      expect((editor as HTMLTextAreaElement).value).toBe("print('hi')\n"),
    );
    // Verify the second api call was to the source endpoint and returned the JSON {content}.
    const sourceCall = apiMock.mock.calls.find(
      (c) => typeof c[0] === "string" && c[0].endsWith("/source"),
    );
    expect(sourceCall).toBeDefined();
    expect(sourceCall?.[0]).toBe("/scripts/1/source");
  });

  it("save for new script sends name + source + language", async () => {
    apiMock.mockResolvedValueOnce({ id: "42" }); // POST /api/scripts
    const user = userEvent.setup();
    renderNew();

    const nameInput = await screen.findByLabelText(/name/i);
    await user.type(nameInput, "my-script");

    await user.click((await screen.findAllByRole("tab", { name: /editor/i }))[0]);
    const editor = (await screen.findAllByTestId("monaco-mock"))[0];
    await user.type(editor, "print('hello')");

    await user.click((await screen.findAllByRole("button", { name: /^save$/i }))[0]);

    await waitFor(() =>
      expect(apiMock.mock.calls.some((c) => c[0] === "/scripts" && (c[1] as { method?: string })?.method === "POST")).toBe(true),
    );
    const [url, opts] = apiMock.mock.calls.find(
      (c) => c[0] === "/scripts" && (c[1] as { method?: string })?.method === "POST",
    )!;
    const body = JSON.parse((opts as { body: string }).body);
    expect(url).toBe("/scripts");
    expect((opts as { method: string }).method).toBe("POST");
    expect(body).toMatchObject({
      name: "my-script",
      source: "print('hello')",
      language: "python",
    });
  });

  it("accepts a dropped .py file and populates editor", async () => {
    renderNew();

    const dropZones = await screen.findAllByTestId("script-dropzone");
    // Pick the visible one (Radix Tabs renders inactive contents but hides them).
    const visible = dropZones.find((el) => !el.closest('[data-state="inactive"]')) ?? dropZones[0];
    const file = new File(["print(1)"], "hello.py", { type: "text/x-python" });
    fireEvent.drop(visible, { dataTransfer: { files: [file] } });

    const editors = await screen.findAllByTestId("monaco-mock");
    await waitFor(() =>
      expect(editors.some((e) => (e as HTMLTextAreaElement).value === "print(1)")).toBe(true),
    );
  });
});
