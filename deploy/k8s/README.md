# Kubernetes manifests

The testbed manifests are rendered by the KELT repository. This directory
holds the namespace and one example:

| File | Content |
|------|---------|
| `namespace.yaml` | the `5g-northbound` namespace |
| `examples/placement-editor.yaml` | ConfigMap, Secret, Deployment and Service for one service |

Every service follows the same pattern:

1. **ConfigMap** with the contract entries marked `sensitive: false`.
2. **Secret** (`Opaque`) with the entries marked `sensitive: true`.
3. **Deployment** that loads both with `envFrom`, so a new variable needs no
   change to the Deployment. Probes as in
   [deployment](../../docs/deployment.md#probes).
4. **Service** of type `ClusterIP`.

`python3 deploy/tools/contracts.py render-k8s <service>` prints the ConfigMap
and the Secret from the service's contract. A service that stores data mounts
the persistent volume listed in
[deployment](../../docs/deployment.md#storage).

`location-app` and `placement-editor` receive their browser settings as
environment variables too: `entrypoint.sh` writes them into `env-config.js`
at start. The file is not mounted from a ConfigMap.

To rotate a secret:

```sh
kubectl -n 5g-northbound edit secret <service>-secrets
kubectl -n 5g-northbound rollout restart deployment <service>
```
