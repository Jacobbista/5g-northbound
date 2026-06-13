# mock-wittra

Demo-only fake of the [Wittra cloud REST API](https://docs.wittra.io/#/howto-integrations-and-api?id=rest-api). Lets the local stack exercise the [`rest-adapter`](../../services/rest-adapter/) without a Wittra account or external connectivity.

Production deployments point the rest-adapter at the real `https://api.wittra.se` and never need this image. It is here so a fresh `make demo` clone shows the Wittra integration path end-to-end.

## What it serves

| Method · path                                                                            | Returns                                       |
|------------------------------------------------------------------------------------------|-----------------------------------------------|
| `GET /health`                                                                            | `{"status":"ok"}`                             |
| `GET /v1/organizations/{org}/projects/{prj}/devices/{device_id}`                         | Wittra-shaped JSON (`payload.location.{latitude, longitude, accuracy, height, level, label}`, `timestamp`, …) |

Authentication is HTTP Basic with `{org_id}:{api_key}`, matching the real Wittra REST API. Unknown org/project/device → `404`.

The reported position is a slow random walk around a fixed reference point (~Turin lab). Two devices are known by default: `wittra-tag-01`, `wittra-tag-02`.

## Configuration

| Variable                     | Default      | Notes                                  |
|------------------------------|--------------|----------------------------------------|
| `MOCK_WITTRA_ORG_ID`         | `demo-org`   | Expected Basic-auth username           |
| `MOCK_WITTRA_API_KEY`        | `demo-key`   | Expected Basic-auth password           |
| `MOCK_WITTRA_PROJECT_ID`     | `demo-prj`   | Required project segment in the URL    |

## Trying it locally

```bash
curl -u demo-org:demo-key \
  http://localhost:8091/v1/organizations/demo-org/projects/demo-prj/devices/wittra-tag-01 \
  | jq .
```

The compose stack wires this service as the upstream for `rest-adapter`; the engine's `wittra=…` adapter entry feeds through both. See [`docs/integrating-a-vendor-rest-api.md`](../docs/integrating-a-vendor-rest-api.md) for the full chain.
