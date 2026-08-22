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
        flush();
        for (const code of codes) {
          if (code === 0) {
            flush();
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
