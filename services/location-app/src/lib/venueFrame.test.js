import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { frameFromBlueprint, gpsToScene, roomToVenue, sceneToGps } from "./venueFrame";

// Tests run from the package root, services/location-app.
const example = JSON.parse(
  readFileSync(resolve(process.cwd(), "../../schema/examples/layout.example.json"), "utf8")
);

describe("venueFrame", () => {
  it("places a room point the way the engine does, rotation included", () => {
    // room-02 is rotated 30 degrees clockwise. The engine test pins AP02 at
    // (23.5, 16 + 2 + cos 30) in the venue frame.
    const bp = { ...example, rooms: [example.rooms[1]] };
    const f = frameFromBlueprint(bp);
    const v = roomToVenue(3, 3, f);
    expect(v.x).toBeCloseTo(23.5, 6);
    expect(v.y).toBeCloseTo(18 + Math.cos(Math.PI / 6), 6);
  });

  it("returns to the same scene point through WGS84", () => {
    const bp = { ...example, rooms: [example.rooms[1]] };
    const f = frameFromBlueprint(bp);
    const ll = sceneToGps(2.5, 1.25, f);
    const back = gpsToScene(ll.lat, ll.lon, f);
    expect(back.x).toBeCloseTo(2.5, 6);
    expect(back.z).toBeCloseTo(1.25, 6);
  });

  it("has no frame without a georef", () => {
    expect(frameFromBlueprint({ version: 3, floor_plans: [{ id: "fp" }], rooms: [] })).toBeNull();
  });
});

describe("frameFromBlueprint without a complete georef", () => {
  it("has no frame when the georef lacks its bearing", () => {
    const bp = {
      version: 3,
      floor_plans: [{ id: "fp", georef: { latitude: 59.4, longitude: 17.9 } }],
      rooms: [{ id: "r", floor_plan_id: "fp", x_m: 0, y_m: 0, width_m: 10, depth_m: 8 }],
    };
    expect(frameFromBlueprint(bp)).toBeNull();
  });
});
