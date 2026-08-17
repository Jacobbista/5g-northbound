// TEMPLATE - committed. Copy this to env-config.js (gitignored) and edit
// the values for your local environment:
//
//   cp env-config.example.js env-config.js
//
// `make demo` does the copy automatically the first time it does not find
// env-config.js. The runtime SPA only reads env-config.js, never the
// .example. In production the file is regenerated at container start from
// env vars (see entrypoint.sh).
//
// Keys here are read by src/config.js via the precedence
//   window.__ENV__  →  import.meta.env  →  hard-coded fallback
// Values left as empty string fall through to the next layer.
window.__ENV__ = {
  // CAMARA gateway base URL. The demo is the only public consumer.
  VITE_CAMARA_API_BASE: "http://localhost:8087",
  // Keycloak (PKCE login).
  VITE_KEYCLOAK_URL: "http://localhost:8180",
  VITE_KEYCLOAK_REALM: "5g-testbed",
  VITE_KEYCLOAK_CLIENT_ID: "location-app",
  // GPS reference for projecting CAMARA area.center back into the local
  // floor frame. MUST match the engine's floor-plan gps_origin.
  VITE_GPS_ORIGIN_LAT: "45.064312",
  VITE_GPS_ORIGIN_LON: "7.659154",
  // Floor plan dimensions in metres (must match the engine's room/floor).
  VITE_FLOOR_W: "13",
  VITE_FLOOR_D: "32",
  // Fix accuracy (m) above which a device renders greyed-out instead of live.
  VITE_ACCURACY_MAX_M: "15",
};
