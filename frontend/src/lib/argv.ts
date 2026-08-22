/**
 * Map a manual-run params dict to language-appropriate argv.
 *
 * Mirrors `kindling.params.argv_for` (Python) verbatim so the in-browser
 * preview matches what the runner actually executes. If the two diverge,
 * the preview becomes a lie — drift must be guarded by tests sharing the
 * same fixtures.
 *
 * - python/bash: positional argv in JSON key insertion order. Keys are
 *   ignored; values are stringified.
 * - node: `--key value` pairs. Booleans: `true` → `--key` (flag-only);
 *   `false` omits the key entirely.
 */

export type ArgvLanguage = "python" | "bash" | "node";

const SUPPORTED: ReadonlyArray<ArgvLanguage> = ["python", "bash", "node"];

export function argvFor(language: string, params: Record<string, unknown> | null | undefined): string[] {
  if (params == null || typeof params !== "object" || Array.isArray(params)) {
    throw new Error(`params must be a dict, got ${params == null ? "null" : Array.isArray(params) ? "array" : typeof params}`);
  }
  if (!SUPPORTED.includes(language as ArgvLanguage)) {
    throw new Error(
      `unsupported language for argv_for: ${JSON.stringify(language)} (expected one of ${JSON.stringify(SUPPORTED)})`,
    );
  }
  if (language === "node") {
    const out: string[] = [];
    for (const [k, v] of Object.entries(params)) {
      if (v === false) continue;
      out.push(`--${k}`);
      if (typeof v !== "boolean") out.push(String(v));
    }
    return out;
  }
  // python / bash: positional, key insertion order preserved.
  return Object.values(params).map((v) => String(v));
}

/** Render argv as `$ <language> <entrypoint> <args…>`. Pure formatter. */
export function commandPreviewFor(language: ArgvLanguage, entrypoint: string | null | undefined, argv: string[]): string {
  const ep = entrypoint?.trim() || "<entrypoint>";
  const tail = argv.length > 0 ? ` ${argv.join(" ")}` : "";
  return `$ ${language} ${ep}${tail}`;
}
