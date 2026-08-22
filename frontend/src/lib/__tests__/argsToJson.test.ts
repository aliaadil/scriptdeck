import { describe, it, expect } from "vitest";
import { argsToJson } from "../argsToJson";

describe("argsToJson", () => {
  it("parses --key value pairs into a flat object", () => {
    expect(argsToJson(["--region", "us-east-1", "--shard", "3"])).toEqual({
      ok: true,
      value: { region: "us-east-1", shard: "3" },
    });
  });

  it("parses --key=value form", () => {
    expect(argsToJson(["--region=us-east-1", "--shard=3"])).toEqual({
      ok: true,
      value: { region: "us-east-1", shard: "3" },
    });
  });

  it("treats a bare --flag with no following value as boolean true", () => {
    expect(argsToJson(["--verbose"])).toEqual({
      ok: true,
      value: { verbose: "true" },
    });
    // Two flags in a row → both are boolean.
    expect(argsToJson(["--verbose", "--dry-run"])).toEqual({
      ok: true,
      value: { verbose: "true", "dry-run": "true" },
    });
  });

  it("preserves quoted values passed through from shlex", () => {
    expect(argsToJson(["--name", "alice cooper", "--greeting", "hi there"])).toEqual({
      ok: true,
      value: { name: "alice cooper", greeting: "hi there" },
    });
  });

  it("returns null value for empty input", () => {
    expect(argsToJson([])).toEqual({ ok: true, value: null });
  });

  it("rejects positional tokens with a clear error", () => {
    const r = argsToJson(["users", "--region", "us-east-1"]);
    expect(r.ok).toBe(false);
    if (r.ok) throw new Error("expected failure");
    expect(r.error).toMatch(/Unexpected positional/i);
  });

  it("rejects dangling = in --key=", () => {
    const r = argsToJson(["--=value"]);
    expect(r.ok).toBe(false);
    if (r.ok) throw new Error("expected failure");
    expect(r.error).toMatch(/empty key/i);
  });

  it("rejects a lone -- token", () => {
    const r = argsToJson(["--"]);
    expect(r.ok).toBe(false);
    if (r.ok) throw new Error("expected failure");
    expect(r.error).toMatch(/empty flag/i);
  });
});
