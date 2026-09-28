# Environment contracts

Each published service declares the environment variables it reads in
`services/<service>/env.contract.yaml`. The image bakes the file and serves it
on `GET /contract`. `deploy/tools/contracts.py` reads every
`services/*/env.contract.yaml`, so a new service needs no registration here.

```yaml
service: <image name>
description: <what the service does>
kind: ui | api | internal
external_origin: <VARIABLE_NAME> | null

required:
  - name: <VARIABLE_NAME>
    description: <meaning>
    sensitive: true | false
    type: string | url | integer | number | boolean | path | json
    example: <placeholder>

optional:
  - name: <VARIABLE_NAME>
    default: "<default, as a string>"
    description: <meaning>
    sensitive: true | false
```

| Field | Meaning |
|-------|---------|
| `kind` | `ui` or `api` for a service reached from outside the cluster, `internal` otherwise |
| `external_origin` | the variable under which KELT records the service's public origin. The image does not read it |
| `sensitive` | `true` routes the value to a Secret, `false` to a ConfigMap. `GET /contract` never returns the default or example of a sensitive entry |
| `type` | the shape of the value, for form rendering and validation |
| `runtime_layer` | `window.__ENV__` for a browser variable that `entrypoint.sh` writes into `env-config.js` |
| `set_by` | who provides the value: `compose` (the default, derived by the deployment), `operator` or `secret` |
| `writable` | the service writes to this path at runtime, so it needs a persistent volume |
| `consumed_by` | the services that read the value, when not only the declaring one |

A variable keeps its name and its sensitivity in every service that declares it.

| Command | Effect |
|---------|--------|
| `make contracts` | lint the contracts and regenerate `sensitivity-manifest.json` |
| `make env-check` | check the compose environment against the contracts |
| `python3 deploy/tools/contracts.py render-k8s <service>` | print the ConfigMap and Secret for one service |

`sensitivity-manifest.json` lists every variable with its routing and the
services that use it. KELT reads it. CI fails when the committed file differs
from the contracts.
