// TEMPLATE - committed. Copy this to env-config.js (gitignored) and edit:
//
//   cp env-config.example.js env-config.js
//
// `make demo` does the copy automatically the first time it does not find
// env-config.js. The runtime app only reads env-config.js, never the
// .example. In production the file is regenerated at container start from
// env vars (see entrypoint.sh).
//
// VITE_MAPBOX_TOKEN: optional Mapbox public access token (starts with "pk.").
//   When set, a "Satellite (Mapbox)" basemap appears in the layer switcher.
//   Free tier: 50k map loads + 200k tile requests / month. Get one at:
//     https://account.mapbox.com/access-tokens/
// VITE_MAP_TILE_URL: optional override for the street-tile URL template.
window.__ENV__ = {
  VITE_MAPBOX_TOKEN: "",
  VITE_MAP_TILE_URL: "",
};
