import { useEffect, useState } from "react";
import keycloak, { initOptions } from "../keycloak";
import { usePosition } from "../hooks/usePosition";
import { DEVICE_LABEL } from "../config";
import { FloorPlanScene } from "./FloorPlanScene";

export function App() {
  const [token, setToken] = useState(null);
  const [authError, setAuthError] = useState(null);
  const { position, error, loading } = usePosition(token);

  useEffect(() => {
    keycloak
      .init(initOptions)
      .then((authenticated) => {
        if (authenticated) setToken(keycloak.token);
        else setAuthError("Authentication failed");
      })
      .catch(() => setAuthError("Keycloak init failed"));
  }, []);

  if (authError) return <div style={{ padding: 24, color: "red" }}>{authError}</div>;
  if (!token) return <div style={{ padding: 24 }}>Authenticating…</div>;

  return (
    <div style={{ fontFamily: "sans-serif" }}>
      <h2 style={{ padding: "8px 16px", margin: 0 }}>5G Positioning Demo</h2>

      {loading && <p style={{ padding: "0 16px" }}>Loading position…</p>}
      {error && <p style={{ padding: "0 16px", color: "red" }}>Error: {error}</p>}

      {position && (
        <div style={{ padding: "0 16px", fontSize: 13 }}>
          <strong>{DEVICE_LABEL}</strong> &nbsp;|&nbsp;
          <strong>lat/lon:</strong> {position.area?.center?.latitude?.toFixed(6)},{" "}
          {position.area?.center?.longitude?.toFixed(6)} &nbsp;|&nbsp;
          <strong>Accuracy:</strong> ±{position.area?.radius?.toFixed(1)}m &nbsp;|&nbsp;
          <strong>Updated:</strong> {position.lastLocationTime}
        </div>
      )}

      <FloorPlanScene position={position} />
    </div>
  );
}
