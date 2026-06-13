# Kubernetes manifests

Skeleton + worked example for the testbed deployment. The deploy portal (TBD)
discovers each service's [env.contract.yaml](../contracts/README.md), reads
operator answers, and emits the manifests in this directory.

## Layout

```
deploy/k8s/
├── README.md
├── namespace.yaml                # 5g-northbound namespace
├── examples/
│   └── placement-editor.yaml     # End-to-end example: ConfigMap + Secret + Deployment + Service
└── <service>.yaml                # Per-service manifests, emitted by the deploy portal
```

## Pattern per service

Each service's manifest contains four resources (concatenated with `---`):

1. **ConfigMap** - every env contract entry with `sensitive: false`.
2. **Secret** - every env contract entry with `sensitive: true`. Always
   `type: Opaque`.
3. **Deployment** - one pod, image pulled from
   `ghcr.io/<owner>/5g-northbound/<image>:<tag>`. `envFrom:` references both
   the ConfigMap and the Secret above so the operator never edits the
   Deployment to add a new env var.
4. **Service** - `ClusterIP`. Cross-service URLs live in the ConfigMap of
   the consumer, never hard-coded in code.

## Rotating a secret

```sh
kubectl -n 5g-northbound edit secret <service>-secrets
kubectl -n 5g-northbound rollout restart deployment <service>
```

Frontend services (positioning-demo, placement-editor) regenerate their
`env-config.js` from env vars at container start via `entrypoint.sh`, so a
restart is enough - no image rebuild.

## Worked example

See [`examples/placement-editor.yaml`](examples/placement-editor.yaml) for the
full shape including the optional Mapbox token (mounted from a Secret and
injected as the `VITE_MAPBOX_TOKEN` env var that the entrypoint reads).
