# Log Formatting — Design

Date: 2026-08-21
Status: Draft
Branch: `kindling/triggers`

## Context

Run logs in the UI are shown as a `<pre>` block with raw text. ANSI
escape codes (colors, bold) from libraries that emit them
(`rich`, `colorama`, `chalk`, `coloredlogs`, etc.) appear as literal
gibberish. Lines that are JSON print as one ugly line. Stack traces
dump 30+ lines that bury the actual error.

This spec adds a `LogViewer` component that parses ANSI, pretty-prints
JSON, and collapses stack traces — all client-side. No backend change.

## Goals

- ANSI colors render with reasonable Tailwind classes.
- Single-line JSON logs render as pretty-printed JSON.
- Python and Node stack traces collapse into a toggle.
- User can switch to raw view.
- Used in both `RunView` and the `ScriptEdit` Logs tab.

## Non-Goals

- Full xterm.js terminal emulation. We only render SGR escapes.
- Log search, filter, follow-tail, or pinning.
- Syntax highlighting inside log lines.
- Storing pre-parsed log content server-side. Browser parses on the fly.
- Cursor / clear-screen escape handling (strip silently).

## Design

### 1. New `LogViewer` component

File: `frontend/src/components/runs/LogViewer.tsx`

Props:

```ts
type LogViewerProps = {
  text: string;          // full accumulated log content
  className?: string;
};
```

Rendering pipeline:

1. Split `text` into lines on `\n`.
2. For each line:
   - **Parse ANSI** (pure function `parseAnsi(text) -> Array<{text, style}>`).
     Handles SGR codes 30-37, 90-97 (fg), 40-47 (bg), 1 (bold), 2
     (dim), 3 (italic), 4 (underline), 9 (strike). Maps to Tailwind
     classes via a small lookup table. Strip unrecognized escapes.
   - **Detect JSON**: if the line (ANSI-stripped, trimmed) starts with
     `{` or `[` and `JSON.parse` succeeds, render pretty-printed.
   - **Detect stack trace**: if line matches `^(\s*)(File\s+".+",\s+line\s+\d+|at\s+.+:\d+:\d+)`,
     mark as trace line. Consecutive trace lines collapse into a
     single `<details>` block.
   - Otherwise render as plain text with ANSI spans.
3. "View raw" toggle replaces the styled view with `<pre>{text}</pre>`.

### 2. Wire into existing views

- `frontend/src/pages/RunView.tsx:107-115` — replace the `<pre>{output}</pre>`
  block with `<LogViewer text={output} />`.
- `frontend/src/pages/ScriptEdit.tsx` — same swap inside the log card
  in the Logs tab (the `<pre className="...bg-[#1e1e1e]...">` block).

### 3. ANSI parser unit test

File: `frontend/src/components/runs/__tests__/ansi.test.ts`

Cases:

- `"\x1b[31mred\x1b[0m"` → one span `[{text:"red", fg:"red"}]`.
- `"\x1b[1;31mbold red\x1b[0m"` → `[{text:"bold red", bold:true, fg:"red"}]`.
- Cursor codes `\x1b[2J`, `\x1b[H` are stripped silently.
- Plain text passes through.

### 4. LogViewer component test

File: `frontend/src/components/runs/__tests__/LogViewer.test.tsx`

Cases:

- Renders ANSI-colored text via spans.
- Detects and pretty-prints a JSON-only line.
- Detects Python trace, collapses to a `<details>` toggle.
- "View raw" toggle reveals plain `<pre>`.

## Files Touched

New:

- `frontend/src/components/runs/LogViewer.tsx`
- `frontend/src/components/runs/__tests__/LogViewer.test.tsx`
- `frontend/src/components/runs/__tests__/ansi.test.ts`

Modify:

- `frontend/src/pages/RunView.tsx`
- `frontend/src/pages/ScriptEdit.tsx`

## Risks

- The parser runs on every render. For very long logs (>100k lines)
  this could be slow. Acceptable for now — Kindling runs are short.
  If it becomes a problem, memoize via `useMemo`.
- Color mapping is opinionated (red for error, yellow for warning).
  Users with custom themes may want overrides. Defer.
- ANSI 256-color and truecolor (`\x1b[38;5;Nm`, `\x1b[38;2;R;G;Bm`)
  are not supported — those escapes are stripped. Document as a
  known limitation.
