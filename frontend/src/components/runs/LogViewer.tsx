import { useMemo, useState } from "react";
import { parseAnsi, type AnsiSpan } from "./ansi";

type Line =
  | { kind: "text"; spans: AnsiSpan[] }
  | { kind: "json"; value: unknown; raw: string }
  | { kind: "trace"; lines: string[] };

const TRACE_RE = /^(\s*)(File ".+", line \d+|at .+:\d+:\d+|Traceback \(most recent call last\))/;

// Common envelope shapes that wrap the actual log line in a string field.
// If JSON parses to an object with one of these keys as a string, render
// the string directly instead of the JSON envelope.
const ENVELOPE_KEYS = ["content", "message", "msg", "text", "output", "data"];

function extractEnvelope(v: unknown): string | null {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  const obj = v as Record<string, unknown>;
  for (const key of ENVELOPE_KEYS) {
    const val = obj[key];
    if (typeof val === "string") return val;
  }
  return null;
}

function classifyCoreText(text: string): Line {
  if (TRACE_RE.test(text)) {
    return { kind: "trace", lines: [text] };
  }
  return { kind: "text", spans: parseAnsi(text) };
}

function classify(text: string): Line | Line[] {
  const stripped = text.replace(/\x1b\[[0-9;]*[A-Za-z]/g, "");
  const trimmed = stripped.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const v = JSON.parse(trimmed);
      const envelope = extractEnvelope(v);
      if (envelope !== null) {
        // Unwrap and split the inner string on newlines so each line
        // renders as its own block. Without this, an envelope that
        // contains embedded \n collapses into a single visible row.
        const out: Line[] = [];
        for (const piece of envelope.split("\n")) {
          if (piece === "") continue;
          out.push(classifyCoreText(piece));
        }
        return out;
      }
      return { kind: "json", value: v, raw: text };
    } catch {
      /* fall through */
    }
  }
  return classifyCoreText(text);
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
      if (Array.isArray(next)) {
        for (const piece of next) {
          out.push(mergeTrace(out[out.length - 1], piece));
        }
      } else {
        out.push(mergeTrace(out[out.length - 1], next));
      }
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
