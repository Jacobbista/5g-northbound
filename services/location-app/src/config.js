const env = window.__ENV__ || {};

const pick = (key, fallback) => env[key] || import.meta.env[key] || fallback;

export const CAMARA_API_BASE = pick("VITE_CAMARA_API_BASE");
export const KEYCLOAK_URL = pick("VITE_KEYCLOAK_URL");
export const KEYCLOAK_REALM = pick("VITE_KEYCLOAK_REALM");
export const KEYCLOAK_CLIENT_ID = pick("VITE_KEYCLOAK_CLIENT_ID");

// Floor plan dimensions in metres (must match the engine's room/floor).
export const FLOOR_W = Number(pick("VITE_FLOOR_W", "20"));
export const FLOOR_D = Number(pick("VITE_FLOOR_D", "30"));
