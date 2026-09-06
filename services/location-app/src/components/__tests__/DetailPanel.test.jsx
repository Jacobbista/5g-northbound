import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DetailPanel } from "../DetailPanel.jsx";

// Stub the anchor-calibration hook (network).
vi.mock("../../hooks/useAnchorCalibration", () => ({
  useAnchorCalibration: () => ({}),
}));

vi.mock("../../hooks/useDeviceDetails", () => ({
  useDeviceDetails: () => ({
    details: { telemetry: {
      latitude: 59.4, longitude: 17.9, accuracy_m: 0.9, altitude: null,
      strategy: "weighted_avg", sources: ["wittra"], lastLocationTime: "2026-08-26T10:00:00Z",
    }, kind: "uwb-tag", source: "wittra" },
    error: null, loading: false,
  }),
}));

vi.mock("../../hooks/useDeviceDiagnostics", () => ({
  useDeviceDiagnostics: () => ({
    diagnostics: {
      battery: 84,
      last_seen: 1700000000,
      x_vendor: { motion: "MOVING", accuracy_value: 0.9, accuracy_kind: "vendor-radius", rssi: [-93, -87] },
    },
    loading: false, error: null,
  }),
}));

const apSelection = (ap) => ({ kind: "ap", ap });

describe("DetailPanel · device diagnostics vocabulary", () => {
  it("renders core fields and collapses x_vendor", () => {
    render(
      <DetailPanel
        selection={{ kind: "device", device: { assetId: "pkg-1", label: "pkg-1", color: "#5dffb0", source: "wittra" } }}
        token="t" onClose={() => {}} frame={null}
      />
    );
    expect(screen.getByText("diagnostics")).toBeInTheDocument();
    // Core field, standard name + unit.
    expect(screen.getByText("84%")).toBeInTheDocument();
    // Vendor-specific extras sit under a collapsed container, raw.
    expect(screen.getByText("vendor-specific")).toBeInTheDocument();
    expect(screen.getByText("MOVING")).toBeInTheDocument();
    // lat/lon always shown; no coordinate toggle
    expect(screen.getByText("lat / lon")).toBeInTheDocument();
    // The device is live (telemetry present) but lastLocationTime is days old:
    // the fix reads as stale, distinct from device liveness, not the current time.
    expect(screen.getByText(/stale/)).toBeInTheDocument();
  });
});

// A georef frame (inverse of gpsToRoomLocal): identity-ish so the anchor's
// room-local (x, y) maps to a finite lat/lon and both rows render.
const FRAME = { georef: true, lat0: 59.4, lon0: 17.9, az: 0, roomX: 0, roomY: 0, fpH: 13.5 };

describe("DetailPanel · anchor identity (P1)", () => {
  it("shows the real vendor hardware id and device class", () => {
    render(
      <DetailPanel
        selection={apSelection({
          id: "AP01",
          technology: "wittra",
          x: 3.2,
          y: 7.1,
          height_m: 2.4,
          vendor: "wittra",
          model: "beacon",
          vendor_device_id: "DEVTAG00000000001",
        })}
        token="t"
        onClose={() => {}}
        frame={FRAME}
      />
    );
    expect(screen.getByText("hardware id")).toBeInTheDocument();
    expect(screen.getByText("DEVTAG00000000001")).toBeInTheDocument();
    expect(screen.getByText("class")).toBeInTheDocument();
    expect(screen.getByText("beacon")).toBeInTheDocument();
    // subtitle carries vendor + class
    expect(screen.getByText("wittra · beacon")).toBeInTheDocument();
    // both coordinate rows, no toggle: room-local metres and the georef'd lat/lon
    expect(screen.getByText("room x / y")).toBeInTheDocument();
    expect(screen.getByText("lat / lon")).toBeInTheDocument();
  });

  it("omits the identity section for an anchor with no vendor identity", () => {
    render(
      <DetailPanel
        selection={apSelection({ id: "AP02", technology: "wifi", x: 1, y: 1 })}
        token="t"
        onClose={() => {}}
        frame={null}
      />
    );
    expect(screen.queryByText("hardware id")).not.toBeInTheDocument();
    // generic subtitle
    expect(screen.getByText("Anchor · wifi")).toBeInTheDocument();
    // no frame -> room-local metres shown, lat/lon row omitted
    expect(screen.getByText("room x / y")).toBeInTheDocument();
    expect(screen.queryByText("lat / lon")).not.toBeInTheDocument();
  });
});
