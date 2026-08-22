# Log Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw `<pre>` log blocks with a `LogViewer` component that renders ANSI colors, pretty-prints JSON lines, and collapses stack traces.

**Architecture:** Frontend-only. Pure-function parsers for ANSI + JSON + stack-trace live next to the `LogViewer` component so they're individually testable. Two views (formatted / raw) toggle inside the component.

**Tech Stack:** React 18 + TypeScript + shadcn/ui + Vitest + Testing Library.

## Global Constraints

- Frontend tests: `cd frontend && npm test -- --run`.
- Lint: `cd frontend && npm run lint`.
- Commit messages: Conventional Commits prefix.
- Spec: docs/superpowers/specs/2026-08-21-log-formatting-design.md.
- No new third-party deps. Pure JS parsers; no xterm.js.
- Used in both `RunView.tsx` and the Logs tab inside `ScriptEdit.tsx`.

---

## File Structure

**Create:**
- `frontend/src/components/runs/LogViewer.tsx` — component, plus internal ANSI / JSON / trace parsers.
- `frontend/src/components/runs/ansi.ts` — `parseAnsi(text)` pure function (kept separate for unit testing).
- `frontend/src/components/runs/__tests__/ansi.test.ts` — parser unit tests.
- `frontend/src/components/runs/__tests__/LogViewer.test.tsx` — component tests.

**Modify:**
- `frontend/src/pages/RunView.tsx` — swap `<pre>{output}</pre>` for `<LogViewer text={output} />`.
- `frontend/src/pages/ScriptEdit.tsx` — same swap in the Logs tab log card.

No backend changes.

---

## Task 1: ANSI parser

**Files:**
- Create: `frontend/src/components/runs/ansi.ts`
- Create: `frontend/src/components/runs/__tests__/ansi.test.ts`

**Interfaces:**
- Consumes: a string possibly containing `\x1b[...m` SGR sequences.
- Produces: `Array<{ text: string; bold?: boolean; italic?: boolean; underline?: boolean; dim?: boolean; fg?: string; bg?: string }>` where `fg`/`bg` are Tailwind color tokens like `"red"`, `"green"`, `"yellow"`, `"blue"`, `"magenta"`, `"cyan"`, `"white"`, `"gray"`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/runs/__tests__/ansi.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { parseAnsi } from "../ansi";

describe("parseAnsi", () => {
  it("passes plain text through", () => {
    expect(parseAnsi("hello world")).toEqual([{ text: "hello world" }]);
  });

  it("parses a single red SGR", () => {
    expect(parseAnsi("\x1b[31mred\x1b[0m")).toEqual([
      { text: "red", fg: "red" },
    ]);
  });

  it("parses combined bold + red", () => {
    expect(parseAnsi("\x1b[1;31mbold red\x1b[0m")).toEqual([
      { text: "bold red", bold: true, fg: "red" },
    ]);
  });

  it("strips cursor-movement codes silently", () => {
    expect(parseAnsi("\x1b[2J\x1b[Hclean")).toEqual([{ text: "clean" }]);
  });

  it("handles a mix of plain and styled spans", () => {
    const out = parseAnsi("a\x1b[32mb\x1b[0mc");
    expect(out).toEqual([
      { text: "a" },
      { text: "b", fg: "green" },
      { text: "c" },
    ]);
  });
});
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd frontend && npm test -- ansi.test.ts`
Expected: FAIL — `parseAnsi` does not exist.

- [ ] **Step 3: Implement `parseAnsi`**

Create `frontend/src/components/runs/ansi.ts`:

```ts
export type AnsiSpan = {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  dim?: boolean;
  fg?: string;
  bg?: string;
};

const FG: Record<number, string> = {
  30: "black", 31: "red", 32: "green", 33: "yellow",
  34: "blue", 35: "magenta", 36: "cyan", 37: "white",
  90: "gray", 91: "red", 92: "green", 93: "yellow",
  94: "blue", 95: "magenta", 96: "cyan", 97: "white",
};

// CSI sequence: ESC [ ... letter
const CSI = /\x1b\[([0-9;]*)([A-Za-z])/g;

export function parseAnsi(input: string): AnsiSpan[] {
  const spans: AnsiSpan[] = [];
  let current: AnsiSpan = { text: "" };
  let i = 0;

  const flush = () => {
    if (current.text.length > 0) {
      spans.push({ ...current, text: current.text });
      current.text = "";
    }
  };

  while (i < input.length) {
    const ch = input[i];
    if (ch === "\x1b" && input[i + 1] === "[") {
      CSI.lastIndex = i;
      const match = CSI.exec(input);
      if (match && match.index === i) {
        const codes = match[1].split(";").filter((s) => s.length).map(Number);
        const final = match[2];
        i += match[0].length;
        if (final !== "m") {
          // Non-SGR (cursor, clear, etc.) — strip silently.
          continue;
        }
        for (const code of codes) {
          if (code === 0) {
            current = { text: "" };
          } else if (code === 1) current.bold = true;
          else if (code === 2) current.dim = true;
          else if (code === 3) current.italic = true;
          else if (code === 4) current.underline = true;
          else if (code === 22) current.bold = false;
          else if (FG[code]) current.fg = FG[code];
        }
        continue;
      }
    }
    current.text += ch;
    i += 1;
  }
  flush();
  return spans.length === 0 ? [{ text: "" }] : spans;
}
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd frontend && npm test -- ansi.test.ts`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/runs/ansi.ts frontend/src/components/runs/__tests__/ansi.test.ts
git commit -m "feat(logs): parse ANSI SGR escape codes into styled spans"
```

---

## Task 2: `LogViewer` component

**Files:**
- Create: `frontend/src/components/runs/LogViewer.tsx`
- Create: `frontend/src/components/runs/__tests__/LogViewer.test.tsx`

**Interfaces:**
- Consumes: `text: string` (the full log), `className?: string`.
- Produces: a styled log block with a "View raw" toggle.

- [ ] **Step 1: Write the failing component test**

Create `frontend/src/components/runs/__tests__/LogViewer.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import { LogViewer } from "../LogViewer";

describe("LogViewer", () => {
  it("renders plain text", () => {
    render(<LogViewer text="hello\nworld" />);
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText("world")).toBeInTheDocument();
  });

  it("pretty-prints a JSON line", () => {
    const text = '{"foo": 1, "bar": [2, 3]}';
    render(<LogViewer text={text} />);
    expect(screen.getByText(/foo/)).toBeInTheDocument();
    expect(screen.getByText(/\[/)).toBeInTheDocument();
  });

  it("toggles to raw view", async () => {
    const user = userEvent.setup();
    render(<LogViewer text="line one" />);
    await user.click(screen.getByRole("button", { name: /view raw/i }));
    expect(document.querySelector("pre")?.textContent).toContain("line one");
  });
});
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd frontend && npm test -- LogViewer.test.tsx`
Expected: FAIL — `LogViewer` does not exist.

- [ ] **Step 3: Implement `LogViewer`**

Create `frontend/src/components/runs/LogViewer.tsx`:

```tsx
import { useMemo, useState } from "react";
import { parseAnsi, type AnsiSpan } from "./ansi";

type Line =
  | { kind: "text"; spans: AnsiSpan[] }
  | { kind: "json"; value: unknown; raw: string }
  | { kind: "trace"; lines: string[] };

const TRACE_RE = /^(\s*)(File ".+", line \d+|at .+:\d+:\d+|Traceback \(most recent call last\))/;

function classify(text: string): Line {
  const stripped = text.replace(/\x1b\[[0-9;]*[A-Za-z]/g, "");
  const trimmed = stripped.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const v = JSON.parse(trimmed);
      return { kind: "json", value: v, raw: text };
    } catch {
      /* fall through */
    }
  }
  if (TRACE_RE.test(text)) {
    return { kind: "trace", lines: [text] };
  }
  return { kind: "text", spans: parseAnsi(text) };
}

function mergeTrace(prev: Line | undefined, current: Line): Line {
  if (prev?.kind === "trace") {
    if (current.kind === "trace") return { kind: "trace", lines: [...prev.lines, ...current.lines] };
    return prev;
  }
  return current;
}

function spanClass(span: AnsiSpan): string {
  const out: string[] = [];
  if (span.bold) out.push("font-bold");
  if (span.italic) out.push("italic");
  if (span.underline) out.push("underline");
  if (span.dim) out.push("opacity-60");
  if (span.fg === "red") out.push("text-red-500");
  if (span.fg === "green") out.push("text-emerald-500");
  if (span.fg === "yellow") out.push("text-amber-500");
  if (span.fg === "blue") out.push("text-sky-500");
  if (span.fg === "magenta") out.push("text-fuchsia-500");
  if (span.fg === "cyan") out.push("text-cyan-500");
  if (span.fg === "white") out.push("text-zinc-100");
  if (span.fg === "gray") out.push("text-zinc-400");
  if (span.fg === "black") out.push("text-zinc-900");
  return out.join(" ");
}

export function LogViewer({ text, className }: { text: string; className?: string }) {
  const [raw, setRaw] = useState(false);

  const lines = useMemo(() => {
    const out: Line[] = [];
    for (const line of text.split("\n")) {
      if (line === "") continue;
      const next = classify(line);
      out.push(mergeTrace(out[out.length - 1], next));
    }
    return out;
  }, [text]);

  if (raw) {
    return (
      <div className={className}>
        <button
          type="button"
          className="mb-2 text-xs text-muted-foreground hover:underline"
          onClick={() => setRaw(false)}
        >
          View formatted
        </button>
        <pre className="whitespace-pre-wrap font-mono text-[13px] leading-relaxed">
          {text}
        </pre>
      </div>
    );
  }

  return (
    <div className={className}>
      <button
        type="button"
        className="mb-2 text-xs text-muted-foreground hover:underline"
        onClick={() => setRaw(true)}
      >
        View raw
      </button>
      <div className="space-y-1 font-mono text-[13px] leading-relaxed">
        {lines.map((line, idx) => {
          if (line.kind === "text") {
            return (
              <div key={idx}>
                {line.spans.map((s, i) => (
                  <span key={i} className={spanClass(s)}>{s.text}</span>
                ))}
              </div>
            );
          }
          if (line.kind === "json") {
            return (
              <pre
                key={idx}
                className="rounded bg-muted/40 p-2 text-xs whitespace-pre-wrap"
              >
                {JSON.stringify(line.value, null, 2)}
              </pre>
            );
          }
          return (
            <details key={idx} className="rounded border bg-muted/30 px-2 py-1 text-xs">
              <summary className="cursor-pointer text-muted-foreground">
                Stack trace ({line.lines.length} lines)
              </summary>
              <pre className="mt-1 whitespace-pre-wrap">{line.lines.join("\n")}</pre>
            </details>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd frontend && npm test -- LogViewer.test.tsx`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/runs/LogViewer.tsx frontend/src/components/runs/__tests__/LogViewer.test.tsx
git commit -m "feat(logs): LogViewer with ANSI/JSON/stack-trace formatting"
```

---

## Task 3: Wire `LogViewer` into RunView and ScriptEdit

**Files:**
- Modify: `frontend/src/pages/RunView.tsx`
- Modify: `frontend/src/pages/ScriptEdit.tsx`

- [ ] **Step 1: Replace the raw `<pre>` in RunView**

In `frontend/src/pages/RunView.tsx`, locate the `<pre>` block at the "output" tab content (~line 107-115). Replace:

```tsx
<pre className="whitespace-pre-wrap leading-relaxed">
  {output || "No output."}
</pre>
```

with:

```tsx
<LogViewer text={output || "No output."} />
```

Add the import at top:

```tsx
import { LogViewer } from "@/components/runs/LogViewer";
```

- [ ] **Step 2: Replace the raw `<pre>` in ScriptEdit Logs tab**

In `frontend/src/pages/ScriptEdit.tsx`, locate the Logs tab's log viewer (~line 436-459, inside `<TabsContent value="logs">`). Replace the inner `<pre>` block with `<LogViewer text={runLog || (runStatus.data?.status === "running" ? "Waiting for output…" : "(no output)")} />`. Add the import at the top alongside other component imports.

- [ ] **Step 3: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests pass.

- [ ] **Step 4: Lint**

Run: `cd frontend && npm run lint`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/RunView.tsx frontend/src/pages/ScriptEdit.tsx
git commit -m "feat(ui): use LogViewer in RunView and ScriptEdit Logs tab"
```

---

## Self-Review Notes

1. **Spec coverage:** ANSI parser → Task 1; JSON pretty-print → Task 2 (classify); stack-trace collapse → Task 2 (TRACE_RE + mergeTrace); raw toggle → Task 2 (useState); wire-in → Task 3. All spec items mapped.
2. **Placeholder scan:** complete code in every step.
3. **Type consistency:** `AnsiSpan` shape used uniformly by `ansi.ts` and `LogViewer.tsx`.
4. **Risk:** the `classify` function strips ANSI before JSON check — `\x1b[31m{"a":1}\x1b[0m` should still parse. Confirmed by the regex in `classify` (strips first, then trims).
5. **Risk:** ANSI 256-color (`\x1b[38;5;Nm`) is silently dropped. Acceptable per spec.
