import { beforeEach, describe, expect, it, vi } from "vitest";

describe("config", () => {
  beforeEach(() => {
    vi.resetModules();
    delete window.__ENV__;
  });

  it("falls back to import.meta.env when __ENV__ is empty", async () => {
    window.__ENV__ = {};
    // import.meta.env is provided by vite test runner via .env file
    const { CAMARA_API_BASE } = await import("./config.js");
    expect(typeof CAMARA_API_BASE).toBe("string");
  });

  it("__ENV__ overrides import.meta.env", async () => {
    window.__ENV__ = { VITE_CAMARA_API_BASE: "http://override:9999" };
    const { CAMARA_API_BASE } = await import("./config.js");
    expect(CAMARA_API_BASE).toBe("http://override:9999");
  });
});
