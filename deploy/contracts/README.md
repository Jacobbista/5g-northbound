# Env contracts

Each production service ships its own `env.contract.yaml` next to its code:

| Service             | Contract                                                                  |
|---------------------|---------------------------------------------------------------------------|
| camara-gateway      | [`../../services/camara-gateway/env.contract.yaml`](../../services/camara-gateway/env.contract.yaml)         |
| positioning-engine  | [`../../services/positioning-engine/env.contract.yaml`](../../services/positioning-engine/env.contract.yaml) |
| wifi-positioning    | [`../../services/wifi-positioning/env.contract.yaml`](../../services/wifi-positioning/env.contract.yaml)     |
| placement-editor    | [`../../services/placement-editor/env.contract.yaml`](../../services/placement-editor/env.contract.yaml)     |
| rest-adapter        | [`../../services/rest-adapter/env.contract.yaml`](../../services/rest-adapter/env.contract.yaml)             |
| positioning-demo    | [`../../services/positioning-demo/env.contract.yaml`](../../services/positioning-demo/env.contract.yaml)     |

The deploy portal discovers these by scanning `services/*/env.contract.yaml`
(no central registry to keep in sync) and renders one form per service.

## Schema

```yaml
service: <image name>
description: <one-paragraph summary, surfaced in the form header>

required:
  - name: <ENV_VAR_NAME>           # POSIX style, uppercase
    description: <prompt shown to the operator>
    sensitive: <true|false>        # true → k8s Secret, false → ConfigMap
    example: <optional placeholder>
    runtime_layer: <optional>      # e.g. "window.__ENV__" when the var is
                                   # read by the browser via env-config.js
                                   # instead of by the backend at startup

optional:
  - name: <ENV_VAR_NAME>
    default: "<built-in default>"  # always quoted as a string
    sensitive: <true|false>
    description: <prompt>
    runtime_layer: <optional>
```

## Conventions

- `sensitive: true` → token / password / API key / client secret. Always
  rendered as a password input in the form and emitted as a `Secret` value
  in the generated manifest.
- `sensitive: false` and stable → `ConfigMap`.
- `runtime_layer: window.__ENV__` flags a frontend var that lives in the
  generated `env-config.js`, not in a backend env block. The portal still
  injects it via env var (consumed by the container's `entrypoint.sh`).
- Variable names follow the convention of the consuming service (no global
  prefix). The schema does not normalise - what the contract says is what
  the container reads.
