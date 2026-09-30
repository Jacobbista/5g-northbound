import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DetailPanel } from "../DetailPanel.jsx";

vi.mock("../../hooks/useAnchorCalibration", () => ({
  useAnchorCalibration: () => ({}),
}));

vi.mock("../../hooks/useDeviceDetails", () => ({
  useDeviceDetails: () => ({
    details: { telemetry: {
      latitude: 59.4, longitude: 17.9, accuracy: 0.9, altitude: 32.6, verticalAccuracy: 0.8,
      strategy: "weighted_avg", sources: ["wittra"], lastLocationTime: "2026-09-29T10:00:00Z",
    }, kind: "uwb-tag", source: "wittra" },
    error: null, loading: false,
  }),
}));

vi.mock("../../hooks/useDeviceDiagnostics", () => ({
  useDeviceDiagnostics: () => ({ diagnostics: null, loading: false, error: null }),
}));

describe("DetailPanel · altitude", () => {
  it("shows the altitude with its vertical error", () => {
    render(
      <DetailPanel
        selection={{ kind: "device", device: { assetId: "pkg-1", label: "pkg-1", color: "#5dffb0", source: "wittra" } }}
        token="t" onClose={() => {}} frame={null}
      />
    );
    expect(screen.getByText(/32\.60 m\s*±0\.80/)).toBeInTheDocument();
  });
});
