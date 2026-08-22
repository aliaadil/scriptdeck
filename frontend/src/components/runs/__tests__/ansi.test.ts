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
