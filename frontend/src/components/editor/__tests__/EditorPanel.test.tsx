import { render, screen, act, fireEvent } from "@testing-library/react";
import { it, expect, vi, beforeEach, afterEach } from "vitest";
import { EditorPanel } from "../EditorPanel";

vi.mock("@monaco-editor/react", () => ({
  default: ({ value, onChange }: any) => (
    <textarea data-testid="monaco" value={value} onChange={(e) => onChange?.(e.target.value)} />
  ),
}));

const mockPut = vi.fn();
vi.mock("@/api/scripts", () => ({
  putScriptFile: (...args: unknown[]) => mockPut(...args),
}));

beforeEach(() => {
  mockPut.mockReset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

// NOTE: the brief's draft used `userEvent.type`, but userEvent v14 hangs under
// vitest fake timers even with `advanceTimers`/`delay: null` (verified in
// isolation against a plain textarea). `fireEvent.change` is what the sibling
// FileTree/FileDialog tests use, and it is a truer model of Monaco anyway:
// the real `onChange` emits the whole document, not one keystroke.
const edit = (value: string) =>
  fireEvent.change(screen.getByTestId("monaco"), { target: { value } });

// `waitFor` is unusable here: RTL v14 detects fake timers by sniffing for a
// `jest` global, finds none under vitest, and falls back to polling with a
// faked setInterval that never fires. Advancing inside `act` flushes both the
// timer callback and the microtasks it awaits, so assertions can be direct.
const tick = (ms: number) => act(async () => {
  vi.advanceTimersByTime(ms);
});

it("debounces saves 1.5s after edit", async () => {
  render(<EditorPanel scriptId={1} path="main.py" initialContent="x" language="python" onSaved={() => {}} onError={() => {}} />);
  edit("xy");
  await tick(1500);
  expect(mockPut).toHaveBeenCalledWith(1, "main.py", "xy");
});

it("does not save before the debounce window elapses", async () => {
  render(<EditorPanel scriptId={1} path="main.py" initialContent="x" language="python" onSaved={() => {}} onError={() => {}} />);
  edit("xy");
  await tick(1400);
  expect(mockPut).not.toHaveBeenCalled();
  expect(screen.getByText("Unsaved")).toBeInTheDocument();
});

it("coalesces rapid edits into a single save of the final content", async () => {
  render(<EditorPanel scriptId={1} path="main.py" initialContent="x" language="python" onSaved={() => {}} onError={() => {}} />);
  edit("xy");
  await tick(1000);
  edit("xyz");
  await tick(1000);
  expect(mockPut).not.toHaveBeenCalled(); // timer restarted by the second edit
  await tick(500);
  expect(mockPut).toHaveBeenCalledTimes(1);
  expect(mockPut).toHaveBeenCalledWith(1, "main.py", "xyz");
});

it("marks the file saved and notifies onSaved after a successful write", async () => {
  const onSaved = vi.fn();
  render(<EditorPanel scriptId={1} path="main.py" initialContent="x" language="python" onSaved={onSaved} onError={() => {}} />);
  edit("xy");
  await tick(1500);
  expect(onSaved).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Saved")).toBeInTheDocument();
});

it("reports save failures through onError and keeps the file dirty", async () => {
  const onError = vi.fn();
  mockPut.mockRejectedValue(new Error("boom"));
  render(<EditorPanel scriptId={1} path="main.py" initialContent="x" language="python" onSaved={() => {}} onError={onError} />);
  edit("xy");
  await tick(1500);
  expect(onError).toHaveBeenCalledWith("boom");
  expect(screen.getByText("Unsaved")).toBeInTheDocument();
});

it("resets content and drops the pending save when the path changes", async () => {
  const { rerender } = render(
    <EditorPanel scriptId={1} path="main.py" initialContent="x" language="python" onSaved={() => {}} onError={() => {}} />,
  );
  edit("xy");
  rerender(
    <EditorPanel scriptId={1} path="other.py" initialContent="other" language="python" onSaved={() => {}} onError={() => {}} />,
  );
  await tick(1500);
  expect(mockPut).not.toHaveBeenCalled();
  expect(screen.getByTestId("monaco")).toHaveValue("other");
});

it("still saves when the parent re-renders with fresh inline callbacks", async () => {
  const { rerender } = render(
    <EditorPanel scriptId={1} path="main.py" initialContent="x" language="python" onSaved={() => {}} onError={() => {}} />,
  );
  edit("xy");
  // A parent re-render (e.g. a polling query) must not restart the debounce.
  await tick(1000);
  rerender(
    <EditorPanel scriptId={1} path="main.py" initialContent="x" language="python" onSaved={() => {}} onError={() => {}} />,
  );
  await tick(500);
  expect(mockPut).toHaveBeenCalledWith(1, "main.py", "xy");
});
