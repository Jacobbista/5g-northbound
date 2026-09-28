# placement-editor

Operator tool for the venue blueprint: floor plans on the map, rooms on the
floor plans, anchors and walls in the rooms. It holds no data. The blueprint
is stored by the positioning-engine, and the editor reads and writes it over
HTTP. The KELT dashboard deploys the published image.

What the blueprint and the bindings contain, and who uses them:
[blueprint and bindings](../../docs/blueprint-vs-bindings.md). How the floor
plan is tied to the Earth: [georeferencing](../../docs/georeferencing.md).

## Sections

| Section | Edits | Stored in |
|---------|-------|-----------|
| World | the floor plan on the map: position, azimuth, size, drawing | `floor_plans[].georef`, `floor_plans[].image` |
| Plan | the rooms on the floor plan, the image scale | `rooms[].{x_m, y_m, width_m, depth_m, rotation_deg}`, `floor_plans[].scale_calibration_refs` |
| Room | anchors per technology, walls, openings, wall height | `rooms[].{anchors, walls, perimeter_openings, wall_height_m}` |

Each section edits one level. Positions in the
inspectors are in the venue frame: metres from the lower-left corner of the
parent level. Every change is written to the engine 600 ms after it is made.
`↓ export` and `↑ import` move the blueprint as a file. An imported version 1
or 2 document is read as written and saved as version 3.

The canvas keeps its working model in screen axes, origin top-left and y down.
`normalizeLayout` converts a blueprint on load and import, `toBlueprint`
converts back on save and export (`src/blueprintFrame.js`, shared with the
location-app and tested against the pair in `schema/examples`).

The Room section shows two tools when an adapter advertises them: `↹ calibrate`
for an adapter with `calibration` (wifi-adapter), and `↻ sync <source>` for
each adapter with `discover`.

| Key | Action |
|-----|--------|
| `V` `W` | select, wall |
| `A` `U` `G` `N` | place a WiFi, UWB, 5G or GNSS anchor |
| `Ctrl`+`Z`, `Ctrl`+`Shift`+`Z` or `Ctrl`+`Y` | undo, redo |
| `Ctrl`+`S` | save now |
| arrows, `Shift`+arrows | move the selection by 0.1 m, 1 m |
| `Delete` | remove the selection |
| `Esc` | cancel the drawing, clear the selection |
| `Alt` while dragging | move without the 0.5 m snap |

## HTTP

| Route | Target |
|-------|--------|
| `GET /health` | liveness |
| `GET /contract` | the environment contract |
| `GET`, `PUT /api/layout` | positioning-engine `/blueprint` |
| `/api/wifi/calibration/*` | wifi-adapter `/calibration/*` |
| `GET`, `PUT /api/wifi/bindings` | wifi-adapter `/bindings` |
| `GET /api/vendor/discover`, `/api/vendor/schema` | vendor-adapter `/discover`, `/schema` |
| `GET /api/capabilities` | positioning-engine `/adapters` |
| `GET /env-config.js` | runtime frontend settings |
| `GET /` | the single-page application |

The routes under `/api` forward the request unchanged and return the upstream
answer, or `502` when the upstream is unreachable. The browser reaches the
adapters only through them.

## Configuration

The variables are in [`env.contract.yaml`](env.contract.yaml):
`POSITIONING_ENGINE_URL`, `WIFI_ADAPTER_URL`, `VENDOR_ADAPTER_URL`, and
`VITE_MAPBOX_TOKEN`, which adds a Mapbox satellite layer. `VITE_MAP_TILE_URL`
replaces the street layer. At start `entrypoint.sh` writes both frontend
variables into `env-config.js`, so they change without a rebuild.

## Access

The service validates no token. It runs behind `oauth2-proxy`, which
authenticates the operator and holds the session
([authentication](../../docs/authentication.md)). The bindings it proxies
contain BSSIDs, so the gate is required.

## Development

```bash
make demo                                   # the editor on http://localhost:3003
cd services/placement-editor && .venv/bin/pytest -q
cd services/placement-editor/frontend && npm test
```

`make test` runs both with the other services.
