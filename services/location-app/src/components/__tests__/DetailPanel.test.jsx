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
    diagnostics: { motion: "MOVING", accuracy_value: 0.9, accuracy_kind: "vendor-radius", rssi: [-93, -87] },
    loading: false, error: null,
  }),
}));

const apSelection = (ap) => ({ kind: "ap", ap });

describe("DetailPanel · device signal quality (P2)", () => {
  it("renders the on-demand signal-quality section", () => {
    render(
      <DetailPanel
        selection={{ kind: "device", device: { assetId: "pkg-1", label: "pkg-1", color: "#5dffb0", source: "wittra" } }}
        token="t" coordMode="absolute" onClose={() => {}} frame={null}
      />
    );
    expect(screen.getByText("signal quality")).toBeInTheDocument();
    expect(screen.getByText(/vendor-radius/)).toBeInTheDocument();
    expect(screen.getByText("MOVING")).toBeInTheDocument();
  });
});

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
        coordMode="relative"
        onClose={() => {}}
      />
    );
    expect(screen.getByText("hardware id")).toBeInTheDocument();
    expect(screen.getByText("DEVTAG00000000001")).toBeInTheDocument();
    expect(screen.getByText("class")).toBeInTheDocument();
    expect(screen.getByText("beacon")).toBeInTheDocument();
    // subtitle carries vendor + class
    expect(screen.getByText("wittra · beacon")).toBeInTheDocument();
  });

  it("omits the identity section for an anchor with no vendor identity", () => {
    render(
      <DetailPanel
        selection={apSelection({ id: "AP02", technology: "wifi", x: 1, y: 1 })}
        token="t"
        coordMode="relative"
        onClose={() => {}}
      />
    );
    expect(screen.queryByText("hardware id")).not.toBeInTheDocument();
    // generic subtitle
    expect(screen.getByText("Anchor · wifi")).toBeInTheDocument();
  });
});
