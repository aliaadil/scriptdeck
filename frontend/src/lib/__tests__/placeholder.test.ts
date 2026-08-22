import { describe, it, expect } from "vitest";
import { isPlaceholderName, UNTITLED_PLACEHOLDER } from "../placeholder";

describe("isPlaceholderName", () => {
  it("returns true for the literal (case-insensitive)", () => {
    expect(isPlaceholderName("Untitled script")).toBe(true);
    expect(isPlaceholderName("untitled script")).toBe(true);
    expect(isPlaceholderName("UNTITLED SCRIPT")).toBe(true);
  });
  it("trims surrounding whitespace", () => {
    expect(isPlaceholderName("  Untitled script  ")).toBe(true);
  });
  it("returns false for real names", () => {
    expect(isPlaceholderName("morning-report")).toBe(false);
    expect(isPlaceholderName("")).toBe(false);
    expect(isPlaceholderName("untitled")).toBe(false);
    expect(isPlaceholderName("Untitled Script!")).toBe(false);
  });
  it("exports the placeholder literal", () => {
    expect(UNTITLED_PLACEHOLDER).toBe("untitled script");
  });
});
