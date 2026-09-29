# Fusion strategies

Positions are fused at two levels:

| Level | Where | Combines |
|-------|-------|----------|
| positioning id | positioning-engine, a pluggable strategy | the measurements the adapters return for one `positioningId`, in the venue frame |
| asset | camara-gateway, fixed | the positions of an asset's capabilities, in WGS84 |

With routing by `source` the engine usually receives one measurement per
positioning id. It fuses several when it fans out to every adapter, for a
request without a source. An asset with several capabilities is always fused
by the gateway.

## Before fusion

The engine completes each measurement from its source's declarations
([adapters](adapters.md#accuracy_class-and-nominal-accuracies)):

- without `accuracy`, the source's `nominalAccuracy`, else the upper bound of
  its `accuracy_class`. Without either the measurement is dropped, since it
  cannot be weighted.
- with `z` but without `verticalAccuracy`, the source's
  `nominalVerticalAccuracy`, when declared. Without it the measurement is kept
  and has no vertical error.
- a `z` from a source that does not declare `z: true` is removed, with its
  `verticalAccuracy`.

## `weighted_avg`

The only strategy implemented, and the engine's default. It is an
inverse-variance weighted mean:

- **Weight:** `wᵢ = cᵢ / aᵢ²`, where `aᵢ` is the horizontal accuracy (floored at
  1 cm) and `cᵢ` the `confidence`, 1 when the source reports none.
- **Position:** `x = Σ wᵢ xᵢ / Σ wᵢ`, the same for `y`.
- **Horizontal accuracy:** the one-sigma error of that mean for independent
  errors, `√(Σ wᵢ² aᵢ²) / Σ wᵢ`. With equal confidences it is
  `1 / √(Σ 1/aᵢ²)`: two 3 m sources give 2.1 m, and adding a source never
  makes the radius larger.
- **Height:** `z` is the mean of the heights with the same weights, over the
  measurements that carry one. A measurement without height takes no part.
- **Vertical accuracy:** `√(Σ wᵢ² σᵢ²) / Σ wᵢ` over the same measurements, where
  `σᵢ` is each height's error. It is absent when one of those heights has no
  error. The weights come from the horizontal accuracy, so a source that is
  sharp horizontally and coarse vertically weighs as much in the height as in
  the plane. The reported vertical error is the error of the height computed.
- **Time:** the fused fix time is the earliest among the measurements.

After fusion the engine attaches what a strategy does not compute: the
established time and `current` from the sources' reporting models
([reporting](adapters.md#reporting-and-reportinginterval)), `lastSeen` as the
latest communication among the sources, and the `diagnostics` of a single
routed source.

## Asset fusion in the gateway

The gateway combines the positions of an asset's capabilities with weights
`1/aᵢ²`, without confidence, which the engine position does not carry. The
radius is `√(1 / Σ wᵢ)`. The altitude and its vertical accuracy are taken as a
pair from the horizontally sharpest position that carries an altitude. The
established time is the earliest among the positions, and the result is
current only when every position is. A capability without a position is left
out, so the asset stays located while one source answers.

## Selecting a strategy

`FUSION_STRATEGY` names the engine's strategy, `weighted_avg` by default.
`FUSION_COMPARE` lists further strategies to run on the same measurements:
their results appear under `fusions` in the engine position, for side-by-side
display, and nothing else reads them. The engine refuses to start with a name
it does not implement.

## Adding a strategy

A strategy is a class with this interface, in
`services/positioning-engine/app/fusion/base.py`. The engine creates one
instance at start and reuses it, so a stateful strategy keeps its per-device
state on the instance, keyed by the positioning id it receives.

```python
class FusionStrategy(Protocol):
    name: str

    def fuse(
        self,
        device_id: str,
        measurements: list[Measurement],
        floor_plan: FloorPlan,
    ) -> Optional[FusedPosition]: ...
```

It is registered in `STRATEGIES` in `app/fusion/registry.py`. It returns
`x`, `y`, `z`, `accuracy`, `verticalAccuracy`, `sources` and `timestamp`, and
leaves the fields attached after fusion alone. The cases in
`services/positioning-engine/tests/test_fusion.py` apply to any strategy: one
measurement passes through, two consistent measurements give a position between
them with a smaller radius, and a height or vertical error is absent when no
measurement supports it.

Candidates that the current strategy does not cover:

- **Kalman filter** across sources, with the measurement accuracy as noise. The
  wifi-adapter already filters its own fixes this way
  ([motion model](blueprint-vs-bindings.md#motion-model-and-algorithm)).
- **Outlier rejection** before the mean, for three or more sources where one
  can be badly wrong.
- **Gating** that keeps the single best measurement, for zones where one
  source is known to dominate.
