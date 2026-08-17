# Latency instrumentation

The northbound stack emits a per-hop latency trace so the platform can break a
single CAMARA call into its stage timings. This document is the **contract** the
aggregator joins on: the correlator that ties hops together, and the structured
log line each hop emits.

Northbound owns the instrumentation (correlator propagation + the log line).
Aggregation into a per-stage breakdown is the platform's (KELT's) job; it reads
the log lines and joins them by correlator.

## Correlator

Every hop is tied together by the CAMARA `x-correlator` header:

- The **gateway mints** it when the client sends none, and echoes it on the
  response (CAMARA Commonalities).
- Internal calls **propagate** it: gateway → engine (`GET /position`), engine →
  adapter (`GET /measurement`, `GET /devices`), and `vendor-adapter` → the vendor
  cloud. So every hop serving one CAMARA call logs the same `correlator`.

## The hop log line

Each service on the data path logs exactly one line per request, at `INFO` on
the `hop` logger, as a single JSON object. The machine-readable contract is
`schema/hop-log.schema.json` (JSON Schema); the aggregator fetches it and
validates against it:

```
https://jacobbista.github.io/5g-northbound/schema/hop-log.schema.json
```

See [Machine-readable contracts](contracts.md) for every published contract, the
Pages vs pinned-tag URLs, and rate-limit notes. Example line:

```json
{
  "event": "hop",
  "service": "camara-gateway",
  "stage": "POST /location-retrieval/v0.5/retrieve",
  "correlator": "b6f1…",
  "status": 200,
  "t_receive": 1723900000.123456,
  "t_emit": 1723900000.145678,
  "span_ms": 22.222
}
```

| Field | Meaning |
|-------|---------|
| `event` | Always `"hop"`; the selector for these lines in a mixed log stream. |
| `service` | Emitting service (`camara-gateway`, `positioning-engine`, `wifi-adapter`, `vendor-adapter`, `synthetic-adapter`). |
| `stage` | `"<METHOD> <path>"` the hop served. |
| `correlator` | The `x-correlator`; the join key across services. |
| `status` | HTTP status the hop returned. |
| `t_receive` / `t_emit` | Unix epoch seconds (float) at request receipt / response emit. |
| `span_ms` | `t_emit - t_receive` in milliseconds; this hop's own service time (includes the time it waited on any downstream hop). |

A hop with no correlator (an internal call outside a traced request) logs
nothing, so the stream stays clean.

## Aggregating (platform side)

Join all lines sharing a `correlator`, order by `t_receive`:

- **End-to-end** = the gateway hop's `span_ms`.
- **Stage breakdown**: a downstream hop's `span_ms` is nested inside its
  caller's, so a stage's own cost is `caller.span_ms - sum(children.span_ms)`.
- **WAN-free internal baseline**: subtract the `adapter → vendor` span from the
  trace. There is no separate deployed mock for this; the vendor hop is just one
  span in the trace, so the internal number is the trace minus that span. A
  deterministic WAN-free repro points `vendor-adapter` at the local `mock-vendor`
  (`make demo` only, never the cluster).
- **Cache**: a `maxAge=0` request bypasses the gateway cache (the fresh path -
  measure this for pipeline latency); a cache hit returns without a downstream
  hop and its `span_ms` is near zero. Do not conflate the two.
