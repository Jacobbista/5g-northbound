import { describe, expect, it } from "vitest";
import { emptyLayoutV2, normalizeLayout, toBlueprint } from "./schema.js";

// The editor writes no georef the operator has not given: an origin at 0,0 or
// an extent of 0 would be a real place or an invalid blueprint.
describe("georef the editor writes", () => {
  it("has none for an empty layout", () => {
    const bp = toBlueprint(emptyLayoutV2());
    expect(bp.floor_plans[0].georef).toBeUndefined();
  });

  it("carries only what a version 1 document had", () => {
    const v1 = { room_w: 13, room_h: 32, gps_origin: { latitude: 59.4042, longitude: 17.9492 } };
    const georef = normalizeLayout(v1).floor_plans[0].georef;
    expect(georef).toEqual({ latitude: 59.4042, longitude: 17.9492 });
  });
});

describe("a version 2 document from the old editor", () => {
  it("loses the placeholders of an unplaced floor plan", () => {
    const v2 = {
      version: 2,
      floor_plans: [
        { id: "fp-01", georef: { latitude: 59.4042, longitude: 17.9492, azimuth_deg: -36.4, width_m: 40, height_m: 30 } },
        { id: "fp-02", georef: { latitude: 0, longitude: 0, azimuth_deg: 0, altitude_m: null, width_m: 0, height_m: 0 } },
      ],
      rooms: [],
    };
    const [placed, unplaced] = normalizeLayout(v2).floor_plans;
    expect(placed.georef.latitude).toBe(59.4042);
    expect(unplaced.georef).toBeUndefined();
  });
});
