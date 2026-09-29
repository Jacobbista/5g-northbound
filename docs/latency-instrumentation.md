# Latency instrumentation

Every service on the position path writes one log line per request, and the
lines of one CAMARA request share a correlator. The platform joins them into
the time spent at each hop. This page is the contract of that join. The stack
writes the lines, and KELT collects and aggregates them.

## Correlator

The CAMARA `x-correlator` header ties the hops together:

- The gateway takes the correlator from the request, or generates one, and
  returns it on the response.
- Every internal call forwards it: gateway to engine, engine to adapter,
  vendor-adapter to the vendor cloud.

Requests without a correlator write no line. The engine's position broadcast
polls the adapters without one, so the stream leaves no trace.

## The line

camara-gateway, positioning-engine, wifi-adapter, vendor-adapter and
synthetic-adapter each write one line per request, at `INFO` on the `hop`
logger, as one JSON object. The schema is
[`schema/hop-log.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/hop-log.schema.json),
also served by the gateway at `GET /contracts/hop-log.schema.json`.

```json
{
  "event": "hop",
  "service": "camara-gateway",
  "stage": "POST /location-retrieval/v0.5/retrieve",
  "correlator": "b6f1c2d4-7a0e-4a3b-9e61-2f1f3c7d8a90",
  "status": 200,
  "t_receive": 1790000000.123456,
  "t_emit": 1790000000.145678,
  "span_ms": 22.222
}
```

| Field | Meaning |
|-------|---------|
| `event` | always `hop`, to select these lines in a mixed log |
| `service` | the service that wrote the line |
| `stage` | method and path of the request served |
| `correlator` | the `x-correlator`, the join key |
| `status` | the HTTP status returned |
| `t_receive`, `t_emit` | epoch seconds when the request arrived and when the response left |
| `span_ms` | `t_emit - t_receive` in milliseconds, including the time spent waiting on downstream hops |

## Aggregation

Group the lines by `correlator` and order them by `t_receive`:

- **End to end**: the gateway line's `span_ms`.
- **Own time of a hop**: its `span_ms` minus the `span_ms` of the hops it
  called.
- **Vendor cloud**: the vendor writes no line, so its time is inside the
  vendor-adapter's own time. A comparison without the network to the vendor
  uses `make demo`, where the vendor-adapter calls the local `mock-vendor`.
- **Caches**: the gateway reuses a position fetched less than
  `LOCATION_CACHE_TTL_S` ago, and the vendor-adapter a vendor response younger
  than the schema's `cacheTtl`. A hit makes no downstream call and has a short
  span. A request with `maxAge: 0` always reaches the engine, which is the case
  to measure for the latency of the whole path.
