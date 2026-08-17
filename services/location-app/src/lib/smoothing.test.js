import { describe, expect, it } from "vitest";
import { ema2d } from "./smoothing";

describe("ema2d", () => {
  it("returns next unchanged when prev is null", () => {
    expect(ema2d(null, { x: 5, z: 7 }, 0.4)).toEqual({ x: 5, z: 7 });
  });

  it("blends prev and next by alpha", () => {
    const out = ema2d({ x: 0, z: 0 }, { x: 10, z: 20 }, 0.5);
    expect(out).toEqual({ x: 5, z: 10 });
  });

  it("alpha=1 collapses to next (no smoothing)", () => {
    expect(ema2d({ x: 0, z: 0 }, { x: 3, z: 4 }, 1)).toEqual({ x: 3, z: 4 });
  });

  it("alpha=0 stays at prev (no update)", () => {
    expect(ema2d({ x: 1, z: 2 }, { x: 99, z: 99 }, 0)).toEqual({ x: 1, z: 2 });
  });

  it("repeated application converges toward next", () => {
    let cur = { x: 0, z: 0 };
    const target = { x: 10, z: 10 };
    for (let i = 0; i < 30; i++) cur = ema2d(cur, target, 0.35);
    expect(cur.x).toBeGreaterThan(9.9);
    expect(cur.z).toBeGreaterThan(9.9);
  });
});
