/**
 * Parse a shlex-tokenized argv list into a flat string-keyed JSON object
 * for the Triggers "params" field.
 *
 * Accepted forms (each token processed left-to-right):
 *   --key value          → { key: value }
 *   --key=value          → { key: value }
 *   --flag               → { flag: "true" }   (next token starts with -- or is missing)
 *
 * Positional tokens and any token not starting with `--` are rejected with
 * a clear error: the resulting object backs `KINDLING_PARAM_<KEY>` env vars
 * on trigger fire, so there is no meaningful mapping for positional input.
 *
 * Empty input (zero tokens) yields `null` — the caller treats this as
 * "no params" and omits the field from the request body.
 *
 * All values are stored as strings. The backend writes env vars verbatim
 * (`KINDLING_PARAM_<KEY>=<value>`), so callers that need typed values
 * should coerce in the script.
 */
export type ArgsToJsonResult =
  | { ok: true; value: Record<string, string> | null }
  | { ok: false; error: string };

export function argsToJson(tokens: string[]): ArgsToJsonResult {
  const out: Record<string, string> = {};
  for (let i = 0; i < tokens.length; i++) {
    const tok = tokens[i];
    if (!tok.startsWith("--")) {
      return {
        ok: false,
        error: `Unexpected positional "${tok}". Triggers expect --key value form (each becomes KINDLING_PARAM_<KEY>=value on fire).`,
      };
    }
    const raw = tok.slice(2);
    if (!raw) {
      return { ok: false, error: "Empty flag (lone \"--\")." };
    }
    if (raw.includes("=")) {
      const eq = raw.indexOf("=");
      const key = raw.slice(0, eq);
      const value = raw.slice(eq + 1);
      if (!key) {
        return { ok: false, error: `Empty key in "${tok}".` };
      }
      out[key] = value;
      continue;
    }
    const next = tokens[i + 1];
    if (next === undefined || next.startsWith("--")) {
      out[raw] = "true";
    } else {
      out[raw] = next;
      i++;
    }
  }
  return { ok: true, value: Object.keys(out).length ? out : null };
}
