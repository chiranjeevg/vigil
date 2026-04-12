import { describe, expect, it, vi, afterEach } from "vitest";
import { api } from "./api";

describe("api.getModels", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("coalesces missing models to an empty array (empty JSON body)", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      text: async () => "{}",
    }) as unknown as typeof fetch;

    const r = await api.getModels();
    expect(r.models).toEqual([]);
    expect(Array.isArray(r.models)).toBe(true);
  });

  it("preserves models when present", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      text: async () =>
        JSON.stringify({
          models: [{ name: "m1", provider: "ollama", size_gb: 1, family: "", parameter_size: "" }],
          ollama_available: true,
        }),
    }) as unknown as typeof fetch;

    const r = await api.getModels();
    expect(r.models).toHaveLength(1);
    expect(r.models[0]?.name).toBe("m1");
    expect(r.ollama_available).toBe(true);
  });
});
