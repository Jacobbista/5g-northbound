const env = window.__ENV__ || {};

const pick = (key, fallback) => env[key] || import.meta.env[key] || fallback;

export const CAMARA_API_BASE = pick("VITE_CAMARA_API_BASE");
export const KEYCLOAK_URL = pick("VITE_KEYCLOAK_URL");
export const KEYCLOAK_REALM = pick("VITE_KEYCLOAK_REALM");
export const KEYCLOAK_CLIENT_ID = pick("VITE_KEYCLOAK_CLIENT_ID");

// CAMARA device identifier this demo asks the location for (phoneNumber form).
export const DEVICE_PHONE_NUMBER = pick("VITE_DEVICE_PHONE_NUMBER", "+390111234567");

// Friendly label drawn above the device marker.
export const DEVICE_LABEL = pick("VITE_DEVICE_LABEL", "wifi-asset-01");

// GPS reference used to project the CAMARA area.center (lat/lon) back onto the
// local floor plan. Must match the origin the provider uses.
export const GPS_ORIGIN_LAT = Number(pick("VITE_GPS_ORIGIN_LAT", "45.064312"));
export const GPS_ORIGIN_LON = Number(pick("VITE_GPS_ORIGIN_LON", "7.659154"));

// Floor plan dimensions in metres (must match the engine's room/floor).
export const FLOOR_W = Number(pick("VITE_FLOOR_W", "20"));
export const FLOOR_D = Number(pick("VITE_FLOOR_D", "30"));
