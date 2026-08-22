import { describe, it, expect } from "vitest";
import { shlex } from "../shell";

describe("shlex", () => {
  it("splits on whitespace", () => {
    expect(shlex("users -p 9000")).toEqual({ tokens: ["users", "-p", "9000"] });
  });
  it("returns empty tokens for empty / whitespace-only input", () => {
    expect(shlex("")).toEqual({ tokens: [] });
    expect(shlex("   ")).toEqual({ tokens: [] });
  });
  it("respects double quotes", () => {
    expect(shlex('"hello world" foo')).toEqual({
      tokens: ["hello world", "foo"],
    });
  });
  it("respects single quotes (literal, no escapes inside)", () => {
    expect(shlex("'a\\nb' b")).toEqual({ tokens: ["a\\nb", "b"] });
  });
  it("supports backslash escapes outside quotes", () => {
    expect(shlex("foo\\ bar baz")).toEqual({ tokens: ["foo bar", "baz"] });
  });
  it("supports backslash escapes inside double quotes", () => {
    expect(shlex('"foo\\"bar" x')).toEqual({ tokens: ['foo"bar', "x"] });
  });
  it("collapses runs of whitespace", () => {
    expect(shlex("  a   b\tc ")).toEqual({ tokens: ["a", "b", "c"] });
  });
  it("errors on unterminated single quote", () => {
    const r = shlex("foo 'unterminated");
    expect(r.error).toMatch(/single quote/i);
  });
  it("errors on unterminated double quote", () => {
    const r = shlex('foo "unterminated');
    expect(r.error).toMatch(/double quote/i);
  });
  it("preserves empty quoted strings as empty tokens", () => {
    // "" with two adjacent whitespace boundaries = empty token between
    expect(shlex('a "" b')).toEqual({ tokens: ["a", "", "b"] });
  });
});
