# placement-editor

Operator-facing service that owns the floor-plan / room / anchor layout JSON. Lives in this repository so the published image can be pulled by the [`kelt`](https://github.com/Jacobbista/kelt) dashboard - keeping a single source for the artefact, while the testbed only consumes it.

`positioning-demo` is the **end-user / CAMARA consumer**; `placement-editor` is the **operator** sibling. They never talk to each other directly - only through the shared `layout.json` file the editor writes and the demo (and the engine) read.

## Status

`v0.3.0` - layer-aware three-section editor. The operator walks through three layers of abstraction, each editable only in its own section:

| Section | Edits | Shows | Output |
|---|---|---|---|
| **① World** | Area on the world map: lat/lon, azimuth, width/height, reference image | Satellite or street tiles, address autocomplete, geolocation marker, coords readout | `floor_plans[i].{georef, image}` |
| **② Plan** | Rooms positioned on the floor plan | Reference image as background, rooms as draggable rectangles | `rooms[i].{x_m, y_m, width_m, height_m, label}` |
| **③ Room** | Anchors per technology + walls + room dims | Metric SVG of the selected room | `rooms[i].{anchors, walls}` |

A single section never mixes layers: step 1 never shows individual APs; step 3 never lets you move the building. The error budget of the positioning system is therefore bounded by *one* georeference survey instead of being summed across many per-AP placements on a global map.

## ① World - area on the map

```
+-------------------------------------------------------------+
| [address search ▼]  [📍 me]  [▢ rectangle]  [+ reference]   |
| ─────────────────── Leaflet map (satellite | street) ────── |
|                                                             |
|   [no area defined yet]                                     |
|   Upload an architectural image, or draw a rectangle.       |
|                                                             |
|                  + you-are-here marker (after 📍 me)        |
|                                                             |
|   place · region · country                                  |
|   cursor / centre / zoom                                    |
+-------------------------------------------------------------+
```

- **Two creation paths, mutually exclusive**:
  - **Upload reference image** → the image (a real-scale floor plan) becomes the area. Defaults to 20 × 20 m, centred on the current map view, opacity slider in the toolbar.
  - **▢ rectangle** → a 20 × 20 m polygon centred on the map view, no image attached.
- **View vs edit mode** - once the area exists, the map opens in *view* mode: the polygon (or image) is rendered but the handles are hidden, so the operator can pan / zoom / search without ever dragging the area by accident. A toolbar button toggles between **✎ edit area** and **✓ done**; handles appear only while editing.
- **Handles** (visible only in edit mode):
  - Blue **move** at the centre.
  - Orange **rotate** above the area (snap 1°).
  - Green **corner resize** ×4 (BL / BR / TR / TL, snap 0.5 m, opposite corner stays anchored, rotation-aware math).
- **Address autocomplete** uses Nominatim with debounce + rate-limit; up to 5 results, each labelled *city · region · country*.
- **📍 me** drops a blue location marker (with the browser's accuracy ring) and flies the map there. The area's origin is *not* changed by this gesture - it is an inspection aid, not a calibration.
- **Coords readout** (bottom-left) shows the reverse-geocoded *place · region · country* for the centre plus cursor + centre + zoom. The box is text-selectable so coordinates can be copied directly.

The sidebar always shows the numeric truth (lat / lon / azimuth / altitude / width / height in metres) - gestures and inputs are interchangeable.

## ② Plan - rooms on the floor plan

Shows the area's reference image (or a dashed rectangle if there is none) as the background, scaled to its real dimensions in metres. Each room belonging to the current floor plan is rendered as a coloured rectangle on top, draggable to position.

The sidebar lists every room, with `+ add room` / remove buttons, and an inspector for the selected room (label, x_m, y_m, width_m, height_m). Inspector numeric inputs commit on blur / Enter only.

## ③ Room - anchors in a single room

The familiar metric SVG editor, scoped to the room selected in step 2. Top-down 2D view (1 unit = 1 metre). Tools in the header:

| Tool       | Hotkey | Gesture |
|------------|--------|---------|
| Select     | `V`    | click to select; drag AP / wall endpoints to move; click empty canvas to deselect |
| + WiFi     | `A`    | click on canvas places one WiFi AP at the cursor (snaps to 0.5 m) |
| + UWB      | `U`    | click on canvas places one UWB / Wittra anchor |
| + 5G       | `G`    | click on canvas places one 5G gNB reference |
| + GNSS     | `N`    | click on canvas places one GNSS reference |
| + Wall     | `W`    | drag from start to end to draw a wall segment |
| + Room     | `R`    | drag opposite corners; commits four perimeter walls in a single undo step |

Sidebar exposes the room's metric width / depth, anchor groups per technology, walls list, and an inspector for the selected item.

### Keyboard reference

```
V / A / U / G / N / W / R    pick tool
Ctrl/Cmd + Z                 undo
Ctrl/Cmd + Shift + Z (or Ctrl+Y)   redo
Ctrl/Cmd + S                 save
← ↑ ↓ →                      nudge selected AP by 0.1 m
Shift + arrows               nudge by 1.0 m
Delete / Backspace           remove selected item
Escape                       cancel current draw / clear selection / switch to Select
Alt during drag              bypass snap-to-grid
```

### History semantics

A single drag collapses into one undoable step via a transient stack - intermediate pointer-move samples are not pushed. Typing in text/number inputs commits on blur, never per keystroke. After save, the saved snapshot becomes the new clean baseline; history is preserved so you can undo past the save.

## Schema (layout.json, v2)

```json
{
  "version": 2,
  "floor_plans": [
    {
      "id":    "fp-01",
      "label": "Polito DAUIN - Floor 1",
      "image": { "data_url": "data:image/png;base64,…", "opacity": 0.7, "filename": "fp01.png" },
      "georef": {
        "latitude":    45.064312,
        "longitude":   7.659154,
        "azimuth_deg": 12.0,
        "altitude_m":  240.0,
        "width_m":     85.0,
        "height_m":    42.0
      }
    }
  ],
  "rooms": [
    {
      "id":            "room-01",
      "label":         "Lab A",
      "floor_plan_id": "fp-01",
      "x_m":           12.0,
      "y_m":           8.0,
      "width_m":       13.0,
      "height_m":      32.0,
      "rotation_deg":  0.0,
      "anchors": [
        { "id": "AP07",  "technology": "wifi",   "x": 2.0, "y": 3.0, "height_m": 2.7, "coverage_m": 30 },
        { "id": "UWB01", "technology": "wittra", "x": 5.0, "y": 4.0, "height_m": 3.0, "coverage_m": 15 }
      ],
      "walls": [
        { "id": "W01", "x1": 1.0, "y1": 1.0, "x2": 5.0, "y2": 1.0, "thickness": 0.2 }
      ]
    }
  ]
}
```

### Backward compatibility

Legacy v1 layouts (top-level `room_w / room_h / gps_origin / aps / walls / floor_plan_image`) are normalised into a single `floor_plans[0]` + `rooms[0]` at read time, so existing fixtures keep loading. Writes always emit v2 **plus** the legacy top-level keys derived from the first floor plan + first room, so the positioning-demo (which still reads `layout.aps`, `layout.gps_origin`, etc.) keeps working unchanged until it migrates to v2 itself.

## HTTP surface

| Method · path        | Returns                                    | Notes                                          |
|----------------------|--------------------------------------------|------------------------------------------------|
| `GET  /health`       | `{"status":"ok"}`                          | Liveness                                       |
| `GET  /api/layout`   | layout JSON                                | Reads `LAYOUT_FILE`. `404` if file missing     |
| `PUT  /api/layout`   | `{"status":"ok","path":"…"}`               | Overwrites `LAYOUT_FILE`. Schema is `extra="allow"` so unknown fields round-trip |
| `GET  /`             | bundled SPA                                | The Vite-built React frontend                  |

Live OpenAPI docs at `http://localhost:3003/docs` once the stack is running.

## Configuration

| Variable           | Default                                                       | Notes                                                                  |
|--------------------|---------------------------------------------------------------|------------------------------------------------------------------------|
| `LAYOUT_FILE`      | `/app/data/layout.json`                                       | Path the editor reads from and writes to. Mount the same artefact on the engine and demo so changes flow through |
| `VITE_MAP_TILE_URL`| `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png` (frontend env) | Override the **street** tile provider for the World step. The satellite layer is ESRI World Imagery and is not overridable yet |

## Local development

```bash
make demo                  # full stack, including this service on :3003
cd placement-editor && pytest                    # 5 backend tests
cd placement-editor/frontend && npm test         # 21 frontend tests
```

The compose service mounts the demo's `public/layout.json` so the editor reads/writes the same file the demo's scene fetches - round-trip works end to end on a single machine.

**File-permission gotcha on bind-mounted writes:** the editor runs as `uid 1001` inside the container. If the host file is owned by your user, the container can read it but writing fails with `PermissionError`. One-shot fix on the dev machine:

```bash
chmod 666 positioning-demo/public/layout.json
```

In Kubernetes use a ConfigMap (read-only at runtime - apply via `kubectl apply -f cm.yaml`) for the engine/demo consumers, and a separate PVC mounted only on the editor pod with the right `fsGroup` for writes.

## Limits + roadmap

- **Image rotation** uses Leaflet's stock `ImageOverlay`, which is axis-aligned only. A rotated area stretches the image - fine as a calibration aid, not visual fidelity. Plugin path: `leaflet-imageoverlay-rotated` (deferred).
- **Multi-floor-plan UI** (add / remove / pick) is absent. Schema supports it; today the editor exposes a single `floor_plans[0]`.
- **PlanCanvas corner-resize and room rotation** are inspector-input only. Pointer gestures are limited to drag-to-move for now.
- **Outside-room references** (5G gNB outdoor, GNSS): schema/UI design deferred until a real 5G/GNSS source materialises.

## Auth (planned)

The scaffold does not validate JWTs. Production deployments MUST front the service with a Keycloak-protected ingress and the realm role `placement-admin` (distinct from the `camara-location-read` role used by CAMARA consumers, so a positioning client cannot mutate placement). When the JWT middleware is wired in directly, this README is updated to document the env vars.

## See also

- [`docs/data-contracts.md` § Placement-editor API](../docs/data-contracts.md#placement-editor-api)
- [`docs/api-reference.md`](../docs/api-reference.md) - one-row-per-endpoint index
- [`docs/architecture.md`](../docs/architecture.md) - service topology diagram
