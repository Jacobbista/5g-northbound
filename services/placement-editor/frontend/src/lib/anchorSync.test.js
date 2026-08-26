import { describe, it, expect } from "vitest";
import { upsertVendorAnchor } from "./anchorSync.js";

const spec = {
  vendor_device_id: "DEVTAG00000000001",
  label: "0036",
  x: 3.2,
  y: 7.1,
  height_m: 2.4,
  device_type: "beacon",
  vendor: "wittra",
};

describe("upsertVendorAnchor", () => {
  it("creates a new anchor carrying the real vendor identity", () => {
    const out = upsertVendorAnchor([], spec, "AP01");
    expect(out).toHaveLength(1);
    const a = out[0];
    expect(a.id).toBe("AP01");
    expect(a.technology).toBe("wittra");
    expect(a.vendor_device_id).toBe("DEVTAG00000000001");
    // model is the device class from the cloud
    expect(a.model).toBe("beacon");
    expect(a.vendor).toBe("wittra");
    expect(a.label).toBe("0036");
    expect(a.x).toBe(3.2);
    expect(a.y).toBe(7.1);
    expect(a.height_m).toBe(2.4);
  });

  it("updates an existing anchor in place (same vendor id), preserving its editor id", () => {
    const existing = [{
      id: "AP07", technology: "wittra", vendor_device_id: "DEVTAG00000000001",
      x: 1, y: 1, height_m: 0, label: "old", vendor: "wittra", model: "beacon",
    }];
    const moved = { ...spec, x: 9.9, y: 8.8 };
    const out = upsertVendorAnchor(existing, moved, "AP99");
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe("AP07"); // editor id preserved
    expect(out[0].x).toBe(9.9);
    expect(out[0].y).toBe(8.8);
    expect(out[0].model).toBe("beacon");
  });

  it("refreshes identity on an anchor that lacked it, without wiping on absence", () => {
    const existing = [{
      id: "AP03", technology: "wittra", vendor_device_id: "DEVTAG00000000001",
      x: 1, y: 1, height_m: 0, label: "kept",
    }];
    const withModel = upsertVendorAnchor(existing, spec, "AP99");
    expect(withModel[0].model).toBe("beacon");
    // a later sync with no device_type keeps the existing model
    const noType = upsertVendorAnchor(withModel, { ...spec, device_type: undefined }, "AP99");
    expect(noType[0].model).toBe("beacon");
  });

  it("does not crash when the cloud device has no device_type (model empty)", () => {
    const out = upsertVendorAnchor([], { ...spec, device_type: undefined }, "AP01");
    expect(out[0].model).toBe("");
    expect(out[0].vendor).toBe("wittra");
  });
});
