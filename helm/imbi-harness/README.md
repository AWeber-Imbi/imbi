# Imbi Harness Helm Chart

One release is one pool of agent runners (ADR 0022, harness plan section 6.1):
a fixed-size Deployment named after the pool. Each pod runs one chain, deletes
itself, and the ReplicaSet starts a clean pod.

## Before the install

1. A namespace for the runners only, at Pod Security level Baseline:

   ```bash
   kubectl create namespace imbi-runners
   kubectl label namespace imbi-runners pod-security.kubernetes.io/enforce=baseline
   ```

2. In Imbi, as a platform administrator: a service account for the pool, its
   client credential, and the pool (`POST /harness/pools` with the pool name,
   labels, organization allowlist, and the service account slug).
3. A Secret with the client credential (keys `client_id`, `client_secret`), or
   set `poolCredential.clientId` and `poolCredential.clientSecret`.

## Install

```bash
helm install general helm/imbi-harness -n imbi-runners \
  --set imbi.apiUrl=https://imbi.example.com/api \
  --set poolCredential.existingSecret=imbi-pool-general
```

## Egress allowlists

With `networkPolicy.enabled`, a runner pod can connect to an internal address
only when the address is on an egress destination of its chain. Platform
admins manage the destinations in Imbi (Admin, Harness, Egress destinations)
and assign them to agents. Public internet egress does not change.

### Prerequisite

Amazon VPC CNI network policy enforcement must be on
(`enableNetworkPolicy: "true"` on the VPC CNI addon) before you set
`networkPolicy.enabled`. Enforcement turns on every NetworkPolicy that
exists in the cluster, not only these. The chart needs Kubernetes 1.32 or
later (`ValidatingAdmissionPolicy` and pod-bound token claims).

### Tiers

| Tier     | Priority | Action | Peers                                   | Owner       |
| -------- | -------- | ------ | --------------------------------------- | ----------- |
| Admin    | 100      | Accept | `networkPolicy.required` targets        | Helm        |
| Admin    | 200      | Accept | One destination generation (pod label)  | egress-sync |
| Baseline | 10       | Deny   | `networkPolicy.internalRanges` and IMDS | Helm        |
| Baseline | 20       | Accept | `0.0.0.0/0`                             | Helm        |

All of them select only the runner pods of the release namespace
(`app.kubernetes.io/name=imbi-harness`) and are egress only. The
`imbi-harness egress-sync` Deployment writes one Admin 200 policy
(`imbi-harness-dest-<slug>-g<generation>`) for each destination generation,
and deletes an old one when no pod has its label. At claim, the runner labels
its own pod `egress.imbi.aweber.com/<slug>: g<generation>` for each
destination of its chain.

A required target needs a pod selector that equals its Service's
`spec.selector`, and a Service port that equals the container port. LiteLLM
does not (80 to 4000), so it is a Service ClusterIP CIDR. When its Service is
made again, update `networkPolicy.required.litellm.cidr`. The render fails
when a required target that the release needs is empty.

### One owner for manageGlobal

Exactly one release in the cluster sets `networkPolicy.manageGlobal: true`.
That release renders the required and Baseline policies, the egress-sync
Deployment and its RBAC, and the egress-sync admission policy. These apply to
every pool in the namespace. Every release sets `networkPolicy.enabled` and
`networkPolicy.canary`.

The cluster objects have fixed names, and the egress sync manages the
destination policies of the whole cluster for the pods of its own namespace.
Thus egress allowlists work in one runner namespace per cluster. Helm refuses
a second `manageGlobal` release in a different namespace.

### Trust model

- The model is hostile: it controls `Bash` in the pod.
- The runner process is trusted. The projected token is readable by uid 0
  only, and the agent runs as another uid. An admission policy lets the
  token change only the `egress.imbi.aweber.com/` labels of its own pod, with
  no change to the spec or annotations.
- Ceiling: a compromised runner process can label its own pod with any
  existing destination generation.
- The egress-sync token can write only Admin 200 Accept policies with
  `networks` peers inside `internalRanges`, for runner pods, and change or
  delete only its own policies (admission policy, `failurePolicy: Fail`).
- At start, the runner connects to IMDS and to `networkPolicy.canary`. If
  either connects in 60 seconds, it exits and claims nothing.

### Baseline override ceiling

A NetworkPolicy in the runner namespace comes before Baseline and overrides
it. Only cluster admins can make one there. Keep the namespace free of
NetworkPolicy objects.

### Emergency revocation

1. Delete the destination in Imbi. New claims stop getting it at once.
2. Delete the runner pods that have its label. This also stops their open
   connections:

   ```bash
   kubectl delete pods -n imbi-runners -l egress.imbi.aweber.com/<slug>
   ```

### Rollback

Set `networkPolicy.enabled: false` and upgrade. Helm deletes its own policies
and the egress-sync Deployment. Then delete the sync's policies:

```bash
kubectl delete clusternetworkpolicies \
  -l app.kubernetes.io/managed-by=imbi-harness-egress-sync
```

## Egress proxy

With `egressProxy.enabled`, runner pods reach host name egress destinations
through the egress proxy (`ghcr.io/aweber-imbi/imbi-egress-proxy`). The
proxy accepts `CONNECT` with a proxy token from imbi-api, and checks that
the token holds the host (port 443) or a CIDR of its address with the
port, and comes from its live runner pod. CIDR destinations keep working
with the proxy on.
See [Agent runners](https://github.com/AWeber-Imbi/imbi/blob/main/docs/deployment/agent-runners.md#host-name-destinations)
for the clients, DNS trust, key rotation, and troubleshooting.

`egressProxy.enabled` needs `networkPolicy.enabled`: the render fails
without it. Set `egressProxy.enabled` in every release, so that its runner
pods get `IMBI_HARNESS_EGRESS_PROXY_URL`. Only the `manageGlobal` release
renders the proxy Deployment, Service, ServiceAccount, Role (pods `get`,
`list`, `watch` in the release namespace), PodDisruptionBudget, and the
proxy policies. Every runner pod gets `POD_UID` from the downward API.

| Value | Default | What it does |
| --- | --- | --- |
| `egressProxy.enabled` | `false` | Turns on the proxy |
| `egressProxy.host` | `imbi-egress-proxy.<namespace>.svc` | Proxy host that the runners use |
| `egressProxy.port` | `3128` | Proxy port. The Service port equals the container port |
| `egressProxy.adminPort` | `9090` | `/healthz`, `/readyz`, `/metrics` |
| `egressProxy.replicas` | `2` | Proxy replicas |
| `egressProxy.image.repository` | `ghcr.io/aweber-imbi/imbi-egress-proxy` | Proxy image |
| `egressProxy.image.tag` | `latest` | Proxy image tag |
| `egressProxy.secret.existingSecret` | `""` | Secret with the HS256 token key. Required in the `manageGlobal` release |
| `egressProxy.secret.key` | `current` | Key of the current token key. imbi-api has the same value in `IMBI_HARNESS_EGRESS_PROXY_SECRET` |
| `egressProxy.secret.previousKey` | `previous` | Key of the old token key, during a rotation. Optional |
| `egressProxy.resources` | 100m/64Mi, 1/256Mi | Proxy container resources |

The proxy policies select only the proxy pods
(`app.kubernetes.io/name=imbi-egress-proxy`):

| Tier     | Priority | Direction | Action | Peers                                                        |
| -------- | -------- | --------- | ------ | ------------------------------------------------------------ |
| Admin    | 110      | Egress    | Accept | kube-dns (53), `required.kubeApi`, `internalRanges` on TCP   |
| Admin    | 111      | Ingress   | Accept | Runner pods on `egressProxy.port`                            |
| Admin    | 111      | Ingress   | Accept | Every pod on `egressProxy.adminPort` (Prometheus)            |
| Admin    | 111      | Ingress   | Deny   | Every other pod                                              |
| Baseline | 30       | Egress    | Deny   | `internalRanges`, `169.254.0.0/16`, `fd00:ec2::/32`          |

`imbi-harness-required` also accepts the proxy pods on `egressProxy.port`
for the runner pods. Public egress of the proxy stays open.

The runner service account can delete pods (deployment mode) and patch
pods (egress allowlists) in the namespace, which also holds the proxy
pods. Admission policies let it delete and patch only its own pod. Thus
the deployment mode also needs Kubernetes 1.32 or later.

Rollback: set `egressProxy.enabled: false` in every release and upgrade.
Host name destinations then stop working. CIDR destinations do not change.

## Checks

The chart has no CI coverage. Check a change with `helm template` and a dry run
against a cluster.
