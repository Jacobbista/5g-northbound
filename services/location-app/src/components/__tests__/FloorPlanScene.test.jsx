// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Source-level guard. The scene needs WebGL to render, so the one property
// worth pinning is checked on the file itself: a raycast toggle whose "on"
// branch is `undefined` shadows Mesh.prototype.raycast with an own undefined,
// three throws "raycast is not a function" on the next pointer move, and the
// canvas' event pipeline is dead for the rest of the session.
const source = readFileSync(
  fileURLToPath(new URL("../FloorPlanScene.jsx", import.meta.url)),
  "utf8"
);

describe("FloorPlanScene raycast gating", () => {
  it("never restores a raycast by passing undefined", () => {
    expect(source).not.toMatch(/raycast=\{[^}]*:\s*undefined\s*\}/);
  });

  it("gates every inert marker with the same real functions", () => {
    const gated = source.match(/raycast=\{inert \? (\w+) : (\w+)\}/g) ?? [];
    expect(gated.length).toBeGreaterThan(0);
    for (const site of gated) {
      expect(site).toBe("raycast={inert ? NO_RAYCAST : MESH_RAYCAST}");
    }
  });
});
