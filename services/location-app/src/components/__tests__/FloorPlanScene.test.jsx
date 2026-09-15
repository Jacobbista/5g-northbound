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


describe("wifi connection lines", () => {
  it("draws trilateration lines only to wifi anchors, not every visible AP", () => {
    // The `aps` array Scene builds is filtered by the WIFI/UWB visibility
    // toggle only, so with both toggles on it holds UWB anchors too. A
    // wifi-sourced device's connection lines must be built from a
    // technology-filtered set, not that shared array, or a UWB tag's anchors
    // get drawn as if they had trilaterated the wifi asset.
    expect(source).toMatch(/const wifiAps = aps\.filter\(\(a\) => techOfAnchor\(a\) === "wifi"\)/);
    expect(source).toMatch(/<ConnectionLines from={local} aps={wifiAps}/);
    expect(source).not.toMatch(/<ConnectionLines from={local} aps={aps}/);
  });
});


describe("blueprint freshness", () => {
  it("polls the blueprint instead of fetching it once", () => {
    // A one-shot fetch on mount leaves an open tab rendering fixes against
    // whatever frame the room had when the tab loaded. If the georeference
    // changes afterward (placement editor, live), every fix is projected onto
    // the old frame and the dot drifts from the room until a reload re-fetches
    // it once. Polling is the fix; this guards against the fetch reverting to
    // a single call with no re-schedule.
    expect(source).toMatch(/setTimeout\(tick, BLUEPRINT_POLL_MS\)/);
  });

  it("keeps the last-known layout on a failed poll rather than clearing it", () => {
    expect(source).not.toMatch(/catch\(\(\) => \{\s*if \(!cancelled\) setLayout\(null\)/);
  });
});
