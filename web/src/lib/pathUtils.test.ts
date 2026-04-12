import { describe, expect, it } from "vitest";
import { pathsEqual } from "@/lib/pathUtils";

describe("pathsEqual", () => {
  it("compares normalized paths", () => {
    expect(pathsEqual("/a/b", "/a/b/")).toBe(true);
    expect(pathsEqual("C:\\foo\\bar", "c:/foo/bar")).toBe(true);
  });

  it("returns false for nullish", () => {
    expect(pathsEqual(null, "/a")).toBe(false);
    expect(pathsEqual("/a", undefined)).toBe(false);
  });

  it("coerces non-strings so API oddities never throw", () => {
    expect(pathsEqual(42 as unknown as string, "42")).toBe(true);
    expect(pathsEqual("/x", 999 as unknown as string)).toBe(false);
  });
});
