import { beforeEach, describe, expect, it, vi } from "vitest";

describe("config", () => {
  beforeEach(() => {
    vi.resetModules();
    delete window.__ENV__;
  });

  it("falls back to import.meta.env when __ENV__ is empty", async () => {
    window.__ENV__ = {};
    // The repo no longer ships a build-time .env (runtime env-config.js is
    // the configuration surface), so the Vite fallback must be stubbed.
    vi.stubEnv("VITE_CAMARA_API_BASE", "http://vite-fallback:8087");
    const { CAMARA_API_BASE } = await import("./config.js");
    expect(CAMARA_API_BASE).toBe("http://vite-fallback:8087");
    vi.unstubAllEnvs();
  });

  it("__ENV__ overrides import.meta.env", async () => {
    window.__ENV__ = { VITE_CAMARA_API_BASE: "http://override:9999" };
    const { CAMARA_API_BASE } = await import("./config.js");
    expect(CAMARA_API_BASE).toBe("http://override:9999");
  });

  it("GPS origin and floor dims parse to numbers", async () => {
    window.__ENV__ = {
      VITE_GPS_ORIGIN_LAT: "45.1",
      VITE_GPS_ORIGIN_LON: "7.2",
      VITE_FLOOR_W: "13",
      VITE_FLOOR_D: "32",
    };
    const m = await import("./config.js");
    expect(m.GPS_ORIGIN_LAT).toBe(45.1);
    expect(m.GPS_ORIGIN_LON).toBe(7.2);
    expect(m.FLOOR_W).toBe(13);
    expect(m.FLOOR_D).toBe(32);
  });
});
