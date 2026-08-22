import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ScriptEdit } from "../ScriptEdit";

const apiMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: (...args: unknown[]) => apiMock(...args),
  getToken: () => null,
}));

const listScriptsFiles = vi.fn();
const getScriptFile = vi.fn();
const deleteScriptFile = vi.fn();
const createScriptFile = vi.fn();
const updateScriptEntrypoint = vi.fn();
const updateScript = vi.fn();

const triggerRun = vi.fn();
vi.mock("@/api/scripts", () => ({
  listScriptsFiles: (...a: unknown[]) => listScriptsFiles(...a),
  getScriptFile: (...a: unknown[]) => getScriptFile(...a),
  putScriptFile: vi.fn(),
  deleteScriptFile: (...a: unknown[]) => deleteScriptFile(...a),
  createScriptFile: (...a: unknown[]) => createScriptFile(...a),
  updateScriptEntrypoint: (...a: unknown[]) => updateScriptEntrypoint(...a),
  updateScript: (...a: unknown[]) => updateScript(...a),
  triggerRun: (...a: unknown[]) => triggerRun(...a),
}));

vi.mock("@/api/runs", () => ({
  listRuns: (params?: { script_id?: number; status?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.script_id) q.set("script_id", String(params.script_id));
    if (params?.status) q.set("status_filter", params.status);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return apiMock(`/runs${qs ? `?${qs}` : ""}`);
  },
  getRun: vi.fn(),
  cancelRun: vi.fn(),
  listRunGroup: vi.fn(),
}));

vi.mock("@/components/ui/sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
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

const mockScript = {
  id: 1,
  name: "test",
  language: "python",
  source_path: "scripts/1",
  entrypoint: "main.py",
  description: "d",
};

const mockFiles = [
  { path: "main.py", size: 10, updated_at: "2026-01-01T00:00:00Z" },
  { path: "lib/util.py", size: 20, updated_at: "2026-01-01T00:00:00Z" },
];

function renderEditor() {
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

/** The Editor tab content, which is the one holding the file tree. */
const tree = () => screen.getByTestId("file-tree");

describe("ScriptEdit", () => {
  beforeEach(() => {
    apiMock.mockReset();
    apiMock.mockImplementation((path: string) => {
      if (path === "/scripts/1") return Promise.resolve(mockScript);
      return Promise.resolve({});
    });
    listScriptsFiles.mockReset().mockResolvedValue(mockFiles);
    getScriptFile.mockReset().mockImplementation((_id: number, path: string) =>
      Promise.resolve(`# ${path}`),
    );
    deleteScriptFile.mockReset().mockResolvedValue(undefined);
    createScriptFile.mockReset().mockResolvedValue({
      path: "extra.py",
      size: 0,
      updated_at: "2026-01-01T00:00:00Z",
    });
    updateScriptEntrypoint.mockReset().mockResolvedValue(mockScript);
    updateScript.mockReset().mockResolvedValue(mockScript);
    vi.stubGlobal("confirm", vi.fn(() => true));
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 404 }))) as unknown as typeof fetch,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the three tabs once the script loads", async () => {
    renderEditor();
    expect(await screen.findByRole("tab", { name: /editor/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /triggers/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /logs/i })).toBeInTheDocument();
  });

  it("renders the file tree with every file", async () => {
    renderEditor();
    await waitFor(() => expect(tree()).toBeInTheDocument());
    expect(await within(tree()).findByRole("button", { name: "main.py" })).toBeInTheDocument();
    expect(within(tree()).getByRole("button", { name: "util.py" })).toBeInTheDocument();
    // Directory grouping header for the nested file.
    expect(within(tree()).getByText("lib/")).toBeInTheDocument();
  });

  it("opens the entrypoint by default and loads its content", async () => {
    renderEditor();
    await waitFor(() => expect(getScriptFile).toHaveBeenCalledWith(1, "main.py"));
    const editor = (await screen.findAllByTestId("monaco-mock"))[0] as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toBe("# main.py"));
  });

  it("opens a file in the editor when clicked in the tree", async () => {
    const user = userEvent.setup();
    renderEditor();
    const target = await within(await screen.findByTestId("file-tree")).findByRole("button", {
      name: "util.py",
    });
    await user.click(target);

    await waitFor(() => expect(getScriptFile).toHaveBeenCalledWith(1, "lib/util.py"));
    const editor = (await screen.findAllByTestId("monaco-mock"))[0] as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toBe("# lib/util.py"));
  });

  it("fires the entrypoint update when the FileTree select changes", async () => {
    renderEditor();
    await waitFor(() => expect(tree()).toBeInTheDocument());

    const select = (await within(tree()).findByTestId("entrypoint-select")) as HTMLSelectElement;
    await waitFor(() => expect(select.options.length).toBe(2));
    expect(select.value).toBe("main.py");

    fireEvent.change(select, { target: { value: "lib/util.py" } });
    await waitFor(() => expect(updateScriptEntrypoint).toHaveBeenCalledWith(1, "lib/util.py"));
  });

  it("creates a file through the add dialog", async () => {
    const user = userEvent.setup();
    renderEditor();
    await waitFor(() => expect(tree()).toBeInTheDocument());

    await user.click(within(tree()).getByTitle("Add file"));
    await user.type(await screen.findByTestId("file-path-input"), "extra.py");
    await user.click(screen.getByTestId("file-path-submit"));

    await waitFor(() => expect(createScriptFile).toHaveBeenCalledWith(1, "extra.py", ""));
  });

  it("deletes a file from the tree after confirmation", async () => {
    const user = userEvent.setup();
    renderEditor();
    await waitFor(() => expect(tree()).toBeInTheDocument());

    await user.click(await within(tree()).findByLabelText("Delete util.py"));
    await waitFor(() => expect(deleteScriptFile).toHaveBeenCalledWith(1, "lib/util.py"));
  });

  it("saves name and description from the header", async () => {
    const user = userEvent.setup();
    renderEditor();

    const nameInput = (await screen.findByTestId("name-input")) as HTMLInputElement;
    await waitFor(() => expect(nameInput.value).toBe("test"));
    await user.clear(nameInput);
    await user.type(nameInput, "renamed");
    await user.click(screen.getByTestId("save-meta"));

    await waitFor(() =>
      expect(updateScript).toHaveBeenCalledWith(1, { name: "renamed", description: "d" }),
    );
  });

  it("starts a run and switches to the Logs tab", async () => {
    const user = userEvent.setup();
    apiMock.mockImplementation((path: string) => {
      if (path === "/scripts/1") return Promise.resolve(mockScript);
      if (path === "/runs/5") {
        return Promise.resolve({ id: 5, script_id: 1, status: "success", exit_code: 0 });
      }
      return Promise.resolve({});
    });
    triggerRun.mockReset();
    triggerRun.mockResolvedValue({ id: 5, script_id: 1, status: "running", exit_code: null, params_json: null });
    renderEditor();

    await user.click(await screen.findByRole("button", { name: /run/i }));

    await waitFor(() => expect(triggerRun).toHaveBeenCalledWith(1, undefined));
    expect(await screen.findByText("Run #5")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("tab", { name: /logs/i })).toHaveAttribute("aria-selected", "true"));
  });

  it("Logs tab lists recent runs and clicking one loads its log", async () => {
    const user = userEvent.setup();
    const runsResp = [
      { id: 99, script_id: 1, status: "success", exit_code: 0, started_at: "2026-08-21T00:00:00Z", ended_at: "2026-08-21T00:00:01Z", schedule_id: null, trigger_kind: "manual", attempt: 0, retry_group: null },
      { id: 98, script_id: 1, status: "failure", exit_code: 2, started_at: "2026-08-20T00:00:00Z", ended_at: "2026-08-20T00:00:01Z", schedule_id: 7, trigger_kind: "cron", attempt: 0, retry_group: null },
    ];
    apiMock.mockImplementation((path: string) => {
      if (path === "/scripts/1") return Promise.resolve(mockScript);
      if (path.startsWith("/runs?script_id=1")) return Promise.resolve(runsResp);
      if (path === "/runs/98") return Promise.resolve(runsResp[1]);
      if (path === "/runs/98/log") return Promise.resolve({ content: "old log" });
      return Promise.resolve({});
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.endsWith("/runs/98/log")) {
          return Promise.resolve(new Response("old log", { status: 200 }));
        }
        return Promise.resolve(new Response("", { status: 404 }));
      }) as unknown as typeof fetch,
    );

    renderEditor();
    await user.click(await screen.findByRole("tab", { name: /logs/i }));

    // Both recent-run rows are rendered and the selected run header appears.
    expect(await screen.findByTestId("recent-run-99")).toBeInTheDocument();
    expect(screen.getByTestId("recent-run-98")).toBeInTheDocument();
    // No Cancel button on finished rows.
    expect(screen.queryByTestId("cancel-run-99")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("recent-run-98"));
    await waitFor(() =>
      expect(screen.getByText("Run #98")).toBeInTheDocument(),
    );
  });

  it("shows a Cancel button on a stuck running row", async () => {
    const user = userEvent.setup();
    const runsResp = [
      { id: 50, script_id: 1, status: "running", exit_code: null, started_at: "2026-08-22T01:00:00Z", ended_at: null, schedule_id: null, trigger_kind: "manual", attempt: 0, retry_group: null },
    ];
    apiMock.mockImplementation((path: string) => {
      if (path === "/scripts/1") return Promise.resolve(mockScript);
      if (path.startsWith("/runs?script_id=1")) return Promise.resolve(runsResp);
      return Promise.resolve({});
    });

    renderEditor();
    await user.click(await screen.findByRole("tab", { name: /logs/i }));

    // The X icon button for stopping a stuck run is present and labelled.
    expect(await screen.findByTestId("cancel-run-50")).toBeInTheDocument();
    expect(screen.getByLabelText("Cancel run 50")).toBeInTheDocument();
  });

  it("toggles a params textarea via the chevron next to Run", async () => {
    const user = userEvent.setup();
    renderEditor();

    // Chevron labelled "Show params" should be present; textarea should not.
    const chevron = await screen.findByLabelText("Show params");
    expect(screen.queryByTestId("run-params-textarea")).not.toBeInTheDocument();
    await user.click(chevron);
    expect(await screen.findByTestId("run-params-textarea")).toBeInTheDocument();
    // Toggling again hides it.
    expect(screen.getByLabelText("Hide params")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Hide params"));
    expect(screen.queryByTestId("run-params-textarea")).not.toBeInTheDocument();
  });

  it("blocks the run and shows a toast when params JSON is invalid", async () => {
    const user = userEvent.setup();
    triggerRun.mockClear();
    const { toast } = await import("@/components/ui/sonner");
    (toast.error as ReturnType<typeof vi.fn>).mockClear();
    renderEditor();

    await user.click(await screen.findByLabelText("Show params"));
    const textarea = await screen.findByTestId("run-params-textarea") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "{not json" } });

    // Clicking Run with bad JSON must NOT start a run; toast.error fires.
    await user.click(screen.getByRole("button", { name: /^run/i }));
    expect(triggerRun).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(/invalid params json/i),
    );
  });

  it("passes parsed params to triggerRun when Run is clicked with valid JSON", async () => {
    const user = userEvent.setup();
    triggerRun.mockClear();
    renderEditor();

    await user.click(await screen.findByLabelText("Show params"));
    const textarea = await screen.findByTestId("run-params-textarea") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '{"region":"us-east-1","shard":3}' } });

    await user.click(screen.getByRole("button", { name: /^run/i }));

    await waitFor(() =>
      expect(triggerRun).toHaveBeenCalledWith(1, {
        region: "us-east-1",
        shard: 3,
      }),
    );
  });

  it("shows description as read-only text with an edit pencil", async () => {
    renderEditor();
    const display = await screen.findByTestId("description-display");
    expect(display).toHaveTextContent("d");
    expect(screen.getByTestId("edit-description")).toBeInTheDocument();
  });

  it("hides the description input until the pencil toggles edit mode", async () => {
    const user = userEvent.setup();
    renderEditor();
    expect(screen.queryByTestId("description-input")).not.toBeInTheDocument();
    await user.click(await screen.findByTestId("edit-description"));
    expect(await screen.findByTestId("description-input")).toBeInTheDocument();
  });

  it("falls back to an Add-description prompt when the script has none", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/scripts/1")
        return Promise.resolve({ ...mockScript, description: null });
      return Promise.resolve({});
    });
    renderEditor();
    const display = await screen.findByTestId("description-display");
    expect(display).toHaveTextContent(/add description/i);
  });

  it("shows the Saved indicator only when meta is clean", async () => {
    const user = userEvent.setup();
    renderEditor();
    expect(await screen.findByTestId("saved-indicator")).toBeInTheDocument();
    const nameInput = (await screen.findByTestId("name-input")) as HTMLInputElement;
    await user.type(nameInput, "x");
    await waitFor(() =>
      expect(screen.queryByTestId("saved-indicator")).not.toBeInTheDocument(),
    );
  });

  it("uses a language-specific params placeholder for Python scripts", async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(await screen.findByLabelText("Show params"));
    const textarea = (await screen.findByTestId(
      "run-params-textarea",
    )) as HTMLTextAreaElement;
    expect(textarea.placeholder).toMatch(/positional/i);
    expect(await screen.findByTestId("params-hint")).toHaveTextContent(/python/i);
  });

  it("uses a --key value hint for Node scripts", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/scripts/1")
        return Promise.resolve({ ...mockScript, language: "node" });
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    renderEditor();
    await user.click(await screen.findByLabelText("Show params"));
    const hint = await screen.findByTestId("params-hint");
    expect(hint).toHaveTextContent(/--/);
  });
});
