/**
 * Tiny shell-style tokenizer for the Manual Run args input.
 *
 * Splits on whitespace; supports single quotes, double quotes, and
 * backslash escapes (\\, \", \', \ space). Doesn't model every POSIX rule
 * — no brace expansion, no parameter expansion, no escapes inside single
 * quotes — but covers the cases a user reasonably types when manually
 * passing CLI args to a script:
 *
 *   users -p 9000
 *   --region us-east-1 --shard 3
 *   "hello world" 'key=val with space' tag\=lit
 *
 * Returns:
 *   `{ tokens: string[] }` on success, OR
 *   `{ error: string }` when an unterminated quote is encountered.
 *   Empty input yields `{ tokens: [] }`.
 *
 * Pure function — no DOM, no globals. Safe to import server-side if ever
 * needed.
 */
export type ShellResult =
  | { tokens: string[]; error?: undefined }
  | { tokens?: undefined; error: string };

export function shlex(input: string): ShellResult {
  const out: string[] = [];
  let buf = "";
  let inSingle = false;
  let inDouble = false;
  let hasContent = false;

  for (let i = 0; i < input.length; i++) {
    const c = input[i];
    if (inSingle) {
      if (c === "'") {
        inSingle = false;
        hasContent = true;
      } else {
        buf += c;
      }
      continue;
    }
    if (inDouble) {
      if (c === '"') {
        inDouble = false;
        hasContent = true;
      } else if (c === "\\" && i + 1 < input.length) {
        const next = input[i + 1];
        // Inside double quotes, only \" \\ and \$ ` ! are escapes per POSIX;
        // we accept any backslash-quoted char as a literal for usability.
        buf += next;
        i++;
      } else {
        buf += c;
      }
      continue;
    }
    // Unquoted.
    if (c === "'") {
      inSingle = true;
      hasContent = true;
    } else if (c === '"') {
      inDouble = true;
      hasContent = true;
    } else if (c === "\\") {
      if (i + 1 < input.length) {
        buf += input[i + 1];
        hasContent = true;
        i++;
      }
      // Trailing backslash: ignore.
    } else if (/\s/.test(c)) {
      if (hasContent) {
        out.push(buf);
        buf = "";
        hasContent = false;
      }
    } else {
      buf += c;
      hasContent = true;
    }
  }
  if (inSingle) return { error: "Unterminated single quote in args." };
  if (inDouble) return { error: 'Unterminated double quote in args.' };
  if (hasContent) out.push(buf);
  return { tokens: out };
}
