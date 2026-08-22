/** Mirrors backend tests/test_params_argv.py — guards against TS/Python drift. */
import { describe, it, expect } from "vitest";
import { argvFor, commandPreviewFor } from "../argv";

describe("argvFor (mirrors kindling.params.argv_for)", () => {
  it.each([
    // python/bash positional
    ["python", { region: "us", shard: 3 }, ["us", "3"]],
    ["python", {}, []],
    ["bash", { x: "y" }, ["y"]],
    ["bash", { a: 1, b: 2.5, c: true }, ["1", "2.5", "true"]],
    // node --key value
    ["node", { region: "us", shard: 3 }, ["--region", "us", "--shard", "3"]],
    ["node", {}, []],
    // node bool handling
    ["node", { verbose: true, debug: false }, ["--verbose"]],
    ["node", { region: "us", verbose: true }, ["--region", "us", "--verbose"]],
    // insertion order preserved
    ["python", { z: 1, a: 2, m: 3 }, ["1", "2", "3"]],
  ] as const)("%s %o -> %o", (language, params, expected) => {
    expect(argvFor(language, params as Record<string, unknown>)).toEqual(expected);
  });

  it.each(["ruby", "go", "", "PYTHON"])("raises on unsupported language %s", (language) => {
    expect(() => argvFor(language, { x: "y" })).toThrow();
  });

  it("raises on non-dict input", () => {
    expect(() => argvFor("python", null as unknown as Record<string, unknown>)).toThrow();
    expect(() => argvFor("python", undefined as unknown as Record<string, unknown>)).toThrow();
    expect(() => argvFor("python", [] as unknown as Record<string, unknown>)).toThrow();
  });

  it("returns [] for empty dict across all languages", () => {
    expect(argvFor("python", {})).toEqual([]);
    expect(argvFor("bash", {})).toEqual([]);
    expect(argvFor("node", {})).toEqual([]);
  });
});

describe("commandPreviewFor", () => {
  it("renders empty argv without trailing space", () => {
    expect(commandPreviewFor("python", "main.py", [])).toBe("$ python main.py");
  });
  it("joins argv with single spaces", () => {
    expect(commandPreviewFor("python", "main.py", ["alice", "3"])).toBe("$ python main.py alice 3");
  });
  it("falls back when entrypoint is missing", () => {
    expect(commandPreviewFor("node", null, ["--name", "alice"])).toBe("$ node <entrypoint> --name alice");
  });
});
