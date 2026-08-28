# Profile extensions

The stack extends the CAMARA Device Location profile without altering it. The
CAMARA retrieve and verify surfaces stay byte-identical to the profiled specs
(base + overlay), proven by the CI freshness gate. Everything beyond that -
vendor fidelity, engine fusion metadata, anchor calibration - lives on separate,
namespaced extension surfaces.

## The convention

Extension data is grouped under a **named container**, never a field prefix
sprinkled into a CAMARA payload:

- On a shared surface (the position stream), it sits in a named sub-object
  (`diagnostics`).
- Otherwise it is a **dedicated resource** at its own path, declared in its own
  contract.

Each surface has a published, versioned contract, and this page indexes them. A
consumer that ignores the extension containers sees a conformant CAMARA payload.

## Extension surfaces

| Surface | Kind | Contract | Carries |
|---------|------|----------|---------|
| `GET /device-diagnostics/v0/{assetId}` | resource | `spec/private-profile/device-diagnostics.yaml`, `schema/device-diagnostics.schema.json` | On-demand vendor fidelity: link quality, accuracy provenance, motion |
| Position stream `diagnostics` sub-object | stream field | `spec/private-profile/asyncapi-stream.yaml` | Stream-tier motion, carried from the routed source |
| `GET/PUT /assets` | resource | `spec/private-profile/extensions.yaml`, `schema/asset.schema.json` | Asset Identity Map: an asset binds ≥1 positioning capability, fused into one fix |
| `GET /assets/discoverable` | resource | `spec/private-profile/extensions.yaml` | Onboarding candidates not yet mapped to a capability |
| `GET /assets/{assetId}/details` | resource | `spec/private-profile/extensions.yaml` | Engine fusion metadata (strategy, sources, accuracy), fused across capabilities |
| `GET /anchors/calibration` | resource | `spec/private-profile/extensions.yaml` | Per-anchor RF calibration (wifi) |

See [Machine-readable contracts](contracts.md) for the fetch URLs (Pages CDN +
pinned tag).

## Why this is compliant

CAMARA Commonalities admits additive extensions; the discipline is separation
and clear identification. Separation here is by resource and namespace, never by
a field mixed into the core. The CAMARA APIs remain independently valid against
the upstream specs, and the freshness gate is scoped to them so drift is caught.
