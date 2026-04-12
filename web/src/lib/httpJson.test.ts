import { describe, expect, it } from "vitest";
import { parseJsonResponseBody } from "@/lib/httpJson";

describe("parseJsonResponseBody", () => {
  it("returns empty object for empty or whitespace body", () => {
    expect(parseJsonResponseBody("")).toEqual({});
    expect(parseJsonResponseBody("   \n")).toEqual({});
  });

  it("parses valid JSON", () => {
    expect(parseJsonResponseBody('{"a":1}')).toEqual({ a: 1 });
  });

  it("throws on invalid JSON", () => {
    expect(() => parseJsonResponseBody("{not json")).toThrow();
  });
});
