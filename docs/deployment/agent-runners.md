# Agent Runners

Agent tasks run on runner pods in Kubernetes. A runner pod belongs to a
**pool**. Each pool is one release of the `helm/imbi-harness` chart. This
page tells you how to deploy a pool, connect it to Imbi, and find problems.

For the design, see
[ADR 0022](../api/adr/0022-agent-harness-and-secrets-broker.md). For the
agents and tasks that the runners execute, see [Agents](../admin/agents.md)
and [Agent Tasks](../admin/agent-tasks.md).

## How a runner works

A runner pod has two containers. Both use the image
`ghcr.io/aweber-imbi/imbi-harness`. Each Imbi release publishes this image
for amd64 and arm64.

| Container | Process | What it does |
|---|---|---|
| `runner` | `imbi-harness runner` | Registers with imbi-api, claims work, runs the Claude Agent SDK, and sends task events |
| `executor` | `imbi-harness executor` | Gets secrets from imbi-api, clones repositories, and runs `run_with_secret` commands |

The model and its tools run as an unprivileged `agent` user. They cannot
read the runner credentials, the executor socket, or the other container.

A runner holds one **chain** at a time. A chain is a root task and its child
tasks. The runner works like this:

1. It gets an access token with the pool credential, then registers with
   `POST /harness/runners`.
2. It long-polls imbi-api for work. Imbi gives it the oldest queued task
   that its pool can run.
3. It runs the chain to the end.
4. It removes the workspace, then stops. The pool starts a clean pod for the
   next chain.

A runner renews a 60 second lease with heartbeats. When a lease expires,
imbi-api fences the chain, releases its secrets, and puts it back in the
queue.

On `SIGTERM` (an eviction or a node drain), the runner stops its tasks and
cleans up in 20 seconds. imbi-api then puts the chain back in the queue
at once. The chart sets `terminationGracePeriodSeconds` to 30 to give it
this time.

## Prerequisites

- Kubernetes 1.29 or later for `pool.mode: scaledJob`. The `deployment`
  mode has no special version requirement.
- Helm 3.x.
- A running Imbi installation that the runner pods can reach.
- `imbi-api setup-permissions` has run, so `harness_pool:read` exists.
- [KEDA](https://keda.sh/), only for `pool.mode: scaledJob`. The chart does
  not install it.

## Set up a pool

Do these steps once for each pool. The example pool name is `general`.

### 1. Create the namespace

The runner and the executor start as uid 0 with only the `SETUID` and
`SETGID` capabilities. Pod Security level Restricted refuses this. Use a
namespace at level Baseline. Put only runners in this namespace.

```bash
kubectl create namespace imbi-runners
kubectl label namespace imbi-runners \
  pod-security.kubernetes.io/enforce=baseline
```

### 2. Create the pool service account

Each pool has its own service account in Imbi. Its client credential can
only register runners of that pool.

1. Create a service account in Imbi, for example `harness-general`.
2. Issue a client credential for it. Record the client id and the client
   secret.

### 3. Store the credential in a Secret

Create a Secret with the keys `client_id` and `client_secret`:

```bash
kubectl create secret generic imbi-pool-general -n imbi-runners \
  --from-literal=client_id=<client id> \
  --from-literal=client_secret=<client secret>
```

Alternatively, set `poolCredential.clientId` and
`poolCredential.clientSecret`. The chart then creates a Secret named
`<pool>-pool`.

The chart mounts the Secret in the `runner` container only, owned by uid 0
with mode `0400`.

### 4. Register the pool in Imbi

A platform administrator must do this step. Organization administrators
cannot create, change, or delete pools.

```bash
curl -f -X POST https://imbi.example.com/api/harness/pools \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "general",
        "description": "General agent work",
        "labels": [],
        "organizations": [],
        "service_account": "harness-general",
        "exclusive": false
      }'
```

| Field | What to enter |
|---|---|
| `name` | The pool name. Lower case letters, digits, and `-`; up to 63 characters. It must be the same as the chart's pool name |
| `description` | Optional text |
| `labels` | Runner labels, for example `browser`. Lower case letters, digits, `_`, `.`, and `-` |
| `organizations` | Organization slugs that the pool serves. Empty means all organizations |
| `service_account` | The slug of the pool service account from step 2 |
| `exclusive` | See [Labels and exclusive pools](#labels-and-exclusive-pools). Default `false` |

To change a pool, use `PATCH /harness/pools/{name}` with the fields to
change. Each runner uses the new labels and organizations on its next
claim. To delete a pool, use `DELETE /harness/pools/{name}`. Imbi refuses
the delete with `409 pool_in_use` while a runner of the pool is not
offline.

### 5. Configure the model key

The runner sends model calls through a proxy in the pod. The proxy gets the
model API key from the secrets broker. Do these steps in each organization
that the pool serves.

1. Add a binding for the model key, with **Allowed delivery modes** set to
   `file_descriptor` only. See [Secrets](../admin/secrets.md#add-a-binding).
2. Add a grant for the agents, with the purpose `model_inference` and the
   delivery mode `file_descriptor`.
3. Open **Agents > Settings > Platform**.
4. In **Model upstream**, select `anthropic` or `litellm`.
5. Optional: enter the **Base URL** of the upstream. Empty is the Anthropic
   API. The URL must use `https://`, because the model proxy sends the model
   key to it. For a protected in-cluster upstream only, for example a
   LiteLLM gateway in the same cluster, you can use `http://`. To do this,
   turn on **Allow http://** (`model_upstream.allow_insecure_http`).
6. In **Key**, enter the `secret://` reference of the binding. This is
   `model_upstream.key_ref` in the platform configuration.
7. Click **Save version**.

An agent can use its own key instead of the organization's key. Open the
agent, click **Edit**, then **Access**. In **Model key**, select the binding,
and click **Grant** to add its `model_inference` grant. Then save the agent.
The grant applies immediately, but the agent keeps its previous key until
you save it. The binding must allow the delivery mode `file_descriptor`,
and it cannot be a provider key. The agent still uses
the upstream and the base URL of the organization.

### 6. Configure GitHub access

The runner clones project repositories and plugin marketplaces with a
GitHub App token. The agent pushes and opens pull requests with a second
token. Do these steps in each organization that the pool serves.

1. Add a `github_app` binding with the allowed delivery modes
   `file_descriptor` and `environment`.
2. Add a grant with the purposes `workspace_checkout` and
   `marketplace_fetch`, and the delivery mode `file_descriptor`.
3. Add a second grant with the purpose `github_write` and the delivery mode
   `environment`.
4. Select the binding as the agent's GitHub App binding. The agent's
   **Access** tab shows a check for each purpose, and a **Grant** button for
   a missing one.

A grant allows each of its purposes with each of its delivery modes, so the
two grants must stay separate. Exactly one grant must allow a request.

One binding can serve repositories in more than one GitHub organization:

1. Install the GitHub App on each GitHub organization.
2. Remove `installation_id` from the binding locator. Imbi then finds the
   installation of each repository.
3. Optional: list each marketplace and each external plugin repository in
   the binding's `repositories`, as `owner/name`. An empty list allows each
   repository of the installations.

The repositories of one token must all be in one installation.

### 7. Install the chart

```bash
helm install general helm/imbi-harness -n imbi-runners \
  --set imbi.apiUrl=https://imbi.example.com/api \
  --set imbi.mcpUrl=http://imbi-mcp.imbi.svc.cluster.local:8001/mcp \
  --set poolCredential.existingSecret=imbi-pool-general
```

The release name is the pool name, unless you set `pool.name`. The
Deployment, its ServiceAccount, and its Role use the pool name too.

### 8. Check the pool

1. Open **Admin > <organization> Admin > Agent Runners**.
2. Find the pool. Each runner shows its state, labels, chain, last
   heartbeat, and image version.
3. A new runner shows the state `idle`.

## Chart values

These are the values in `helm/imbi-harness/values.yaml`.

### Image

| Value | Default | Description |
|---|---|---|
| `image.repository` | `ghcr.io/aweber-imbi/imbi-harness` | The runner image |
| `image.tag` | `latest` | Use the same version as imbi-api |
| `image.pullPolicy` | `IfNotPresent` | |

### Pool

| Value | Default | Description |
|---|---|---|
| `pool.name` | `""` | The pool name in Imbi. Empty uses the release name |
| `pool.mode` | `deployment` | `deployment` or `scaledJob`. See [Pool modes](#pool-modes). Any other value fails the render |
| `pool.replicas` | `1` | The pool size in `deployment` mode |

### Imbi

| Value | Default | Description |
|---|---|---|
| `imbi.apiUrl` | `""` | **Required.** imbi-api's URL with its route prefix, for example `https://imbi.example.com/api` |
| `imbi.model` | `""` | The model to use when the agent's prompt names none. Empty uses the CLI default |
| `imbi.mcpUrl` | `""` | The URL of imbi-mcp, for example `http://imbi-mcp:8001/mcp`. The runner relays Imbi tools to agents through it. Empty: agents get no Imbi tools |

### Pool credential

| Value | Default | Description |
|---|---|---|
| `poolCredential.existingSecret` | `""` | A Secret with the keys `client_id` and `client_secret` |
| `poolCredential.clientId` | `""` | The client id, when you do not use `existingSecret` |
| `poolCredential.clientSecret` | `""` | The client secret, when you do not use `existingSecret` |

Set `existingSecret`, or set both `clientId` and `clientSecret`. Otherwise
the render fails.

### Private certificate authorities

| Value | Default | Description |
|---|---|---|
| `extraCaCerts.configMap` | `""` | A ConfigMap with a PEM bundle |
| `extraCaCerts.key` | `ca.crt` | The key of the bundle in the ConfigMap |

Use this when MCP servers use certificates from a private CA. The CLI gets
the bundle as `NODE_EXTRA_CA_CERTS`, so plugin MCP servers can verify their
certificates. Without it, these servers fail with "self-signed certificate
in certificate chain".

```bash
kubectl create configmap private-ca -n imbi-runners \
  --from-file=ca.crt=/path/to/root-ca.pem
helm upgrade general helm/imbi-harness -n imbi-runners --reuse-values \
  --set extraCaCerts.configMap=private-ca
```

!!! note
    The bundle applies to the CLI only. The runner's own relay to MCP
    servers that an administrator registered in Imbi does not use it.

### KEDA (`pool.mode: scaledJob` only)

| Value | Default | Description |
|---|---|---|
| `scaledJob.apiUrl` | `""` | imbi-api's URL with its route prefix, as the KEDA operator reaches it. Empty uses `imbi.apiUrl` |
| `scaledJob.pollingInterval` | `30` | Seconds between queue polls |
| `scaledJob.minReplicaCount` | `0` | |
| `scaledJob.maxReplicaCount` | `10` | The largest number of Jobs at one time |
| `scaledJob.successfulJobsHistoryLimit` | `3` | |
| `scaledJob.failedJobsHistoryLimit` | `3` | |
| `scaledJob.idleExitSeconds` | `120` | A Job that claims no chain in this time exits |

### Pod

| Value | Default | Description |
|---|---|---|
| `terminationGracePeriodSeconds` | `30` | Keep it above 20. The runner fences at 20 seconds after `SIGTERM` |
| `work.sizeLimit` | `10Gi` | The size of `/work`: clones, plugins, and task directories |
| `tmp.sizeLimit` | `1Gi` | The size of the runner's `/tmp`. All the tasks of the pod share it, and the runner does not clear it |
| `resources.runner` | 500m / 1Gi requests, 2 / 4Gi limits | The `runner` container |
| `resources.executor` | 100m / 256Mi requests, 2 / 2Gi limits | The `executor` container |
| `nodeSelector` | `{}` | |
| `tolerations` | `[]` | |
| `affinity` | `{}` | |

## Pool modes

### `deployment` (default)

The chart renders a Deployment with `pool.replicas` pods. At the end of its
chain, each runner deletes its own pod. The ReplicaSet then starts a clean
pod.

The runner deletes the pod with a projected service account token. The
chart adds a Role that allows only `delete` on pods in the namespace.

### `scaledJob`

The chart renders a KEDA `ScaledJob`. KEDA starts one Job for each chain
that the pool can claim. Each Job runs one chain, then exits. The chart adds
no pod-delete Role in this mode.

KEDA polls `GET /harness/pools/{name}/queue`. The response is:

```json
{"pool": "general", "queued": 2}
```

`queued` is the number of tasks that a new runner of the pool could claim
now. It uses the same rules as a claim: the pool labels and organizations,
and the free places of each agent under `max_concurrent_tasks`.

KEDA's `metrics-api` scaler cannot get an OAuth token. So the endpoint takes
the pool credential as HTTP Basic credentials. The chart creates a
`TriggerAuthentication` that reads `client_id` and `client_secret` from the
pool Secret.

| Response | Cause |
|---|---|
| 401 | No Basic credentials, or a wrong credential |
| 403 | No pool with this name, or the credential is not the pool's |
| 429 | More than 30 calls a minute for one pool from one source, or more than 600 a minute from one source |

To install a pool in this mode:

1. Install KEDA in the cluster.
2. Make sure the cluster runs Kubernetes 1.29 or later. The executor runs as
   a native sidecar, so the Job completes when the runner exits.
3. Install the chart:

    ```bash
    helm install general helm/imbi-harness -n imbi-runners \
      --set pool.mode=scaledJob \
      --set imbi.apiUrl=https://imbi.example.com/api \
      --set scaledJob.apiUrl=http://imbi-api.imbi.svc.cluster.local:8000/api \
      --set poolCredential.existingSecret=imbi-pool-general
    ```

Set `scaledJob.apiUrl` to the full service name of imbi-api. A short name
such as `imbi-api` does not resolve from the `keda` namespace.

A Job can start for a chain that another runner then takes. That Job claims
nothing, goes offline after `scaledJob.idleExitSeconds`, and exits.

!!! note
    The `scaledJob` mode has been tested only with a Job created by hand
    from its template.

## Labels and exclusive pools

An agent can require runner labels. Set them in the agent editor, in
**Required runner labels**. A runner gets its labels from its pool. Imbi
ignores labels that a runner sends.

A pool claims a task only when the pool has all the labels that the agent
requires.

| `exclusive` | The pool runs |
|---|---|
| `false` | Agents that require no labels, and agents whose required labels the pool has |
| `true` | Only agents that require at least one label, all of them in the pool labels |

Use an exclusive pool for special work, for example a pool with the label
`browser`. General tasks then do not fill its places. In `scaledJob` mode,
an exclusive pool also does not start a Job for every general task.

## Egress allowlists

By default a runner pod can connect to any address, including internal
hosts and the EC2 instance metadata service. The agent's `Bash` tool runs
in that pod. Turn on egress allowlists to block the internal ranges for
runner pods, except for the destinations that you allow.

Enforcement uses the Amazon VPC CNI `ClusterNetworkPolicy`. Imbi is the
source of truth: platform administrators manage the destinations in the
UI, and the `egress-sync` process writes one policy for each destination
generation. Public egress does not change.

### Prerequisites

- EKS with the Amazon VPC CNI network policy agent turned on
  (`enableNetworkPolicy: "true"` on the addon). Before you turn it on,
  check every existing `NetworkPolicy` in the cluster: it starts to apply.
- The chart values in [Egress chart values](#egress-chart-values).
- A destination is a list of IPv4 CIDRs and ports, or a list of host
  names on port 443. Host names need the egress proxy: see
  [Host name destinations](#host-name-destinations).

### Destinations

Open **Admin > Global Admin > Egress Destinations** (platform administrators only).

| Field | What it does |
|---|---|
| Slug | Part of a pod label key and a policy name. Lower case letters, digits, and `-`, at most 63 characters |
| CIDRs | 1 to 25 IPv4 CIDRs inside `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, or `100.64.0.0/10`. No loopback or link-local |
| Host names | Instead of CIDRs: 1 to 25 DNS names, for example `zoekt.example.internal`. No wildcards and no IP addresses. Imbi stores each in lower case IDNA form |
| Ports | Port and protocol (TCP or UDP). One CIDR can have at most 24 port/protocol pairs across all destinations. Always `443/TCP` for host names |
| Global | Every chain gets the destination |
| Organizations | The organizations whose agents may get it. Empty means all. Not used for a global destination |

Assign a destination that is not global to an agent in the agent editor,
in **Egress destinations**. Anyone who can edit the agent can assign the
destinations of the agent's organization.

Each change to the CIDRs, host names, or ports makes a new **generation**. The page
shows a destination as **pending** until `egress-sync` makes the policy of
its current generation. A claim gives only applied generations, so a new
or narrowed destination never gives more access than its policy. A
running chain keeps the generation that it got at its claim.

The pod of a chain has the global destinations and the destinations of the
chain's root agent. A child task whose agent has a destination that the
pod does not have is refused with `egress_destination_missing`.

A destination that agents still have cannot be deleted. Remove it from the
agents first.

### Emergency revocation

1. Delete the destination. New claims stop getting it at once.
2. Delete the runner pods that have it. This ends their open connections:

    ```sh
    kubectl delete pods -n <namespace> -l egress.imbi.aweber.com/<slug>
    ```

### Trust model

The model is not trusted: it controls `Bash` in the pod. The runner and
executor processes are trusted. The runner labels its own pod with the
destinations of its claim, and an admission policy lets it change only
those labels on its own pod. A compromised runner process could label its
pod with any destination generation that exists.

The chart's Baseline policy denies the internal ranges. A `NetworkPolicy`
in the runner namespace takes priority over it, so only cluster
administrators must be able to create one there.

### Egress chart values

| Value | What it does |
|---|---|
| `networkPolicy.enabled` | Turns on egress allowlists for the release. Default `false` |
| `networkPolicy.manageGlobal` | Renders the cluster-wide objects: the required and Baseline policies, the `imbi-harness-egress-sync` Deployment, and its RBAC and admission policy. Set it in one release per cluster: egress allowlists work in one runner namespace per cluster |
| `networkPolicy.canary` | `host:port` of an internal address that runner pods must not reach. Required. At start, the runner checks that connections to this address and IMDS both time out before it claims work. A refused connection counts as reached. If they do not time out within 60 seconds, or the host does not resolve, the runner exits |
| `networkPolicy.internalRanges` | The ranges that Baseline denies (with link-local) |
| `networkPolicy.required.imbiApi`, `.imbiMcp` | Namespace, pod selector (the Service's `spec.selector`), and port. `imbiMcp` is required when `imbi.mcpUrl` is set |
| `networkPolicy.required.kubeApi` | The Kubernetes API Service ClusterIP as a `/32`, and port 443 |
| `networkPolicy.required.litellm` | Optional. An in-cluster model upstream by Service ClusterIP `/32` and Service port |
| `networkPolicy.required.kubeDns` | Defaults to `kube-system`, `k8s-app: kube-dns` |
| `egressProxy.enabled` | Turns on the egress proxy for the release. Needs `networkPolicy.enabled`. Default `false` |
| `egressProxy.host`, `.port` | The proxy address that the runners use. Defaults: the `imbi-egress-proxy` Service, port `3128` |
| `egressProxy.secret.existingSecret` | The Secret with the token key (key `current`) and the optional old key (key `previous`). Required in the `manageGlobal` release |
| `egressProxy.replicas`, `.adminPort`, `.image`, `.resources` | The proxy Deployment (`manageGlobal` release only). Defaults: 2 replicas, admin port `9090` |

The render fails when a required value is missing. See the
[chart README](https://github.com/AWeber-Imbi/imbi/tree/main/helm/imbi-harness#egress-allowlists)
for the tiers and rollback.

### Host name destinations

A CIDR destination allows every host in its CIDRs. A host whose
addresses change, for example an internal load balancer, needs a CIDR
for each subnet that it can use. A host name destination allows only its
names, on TCP port 443.

A network policy cannot match a host name. Thus runner pods reach a host
name destination only through the **egress proxy**:

1. At claim, imbi-api signs a **proxy token**. The token holds the host
   names of the chain, the CIDRs of the chain grouped by their TCP ports,
   and the uid of the runner pod. The runner sends its pod uid only when
   the egress proxy is on, so a pool with the proxy off gets no token.
2. The runner puts the proxy URL, with the token, in the environment of
   the agent's commands.
3. A client sends `CONNECT <host>:<port>` to the proxy. The proxy resolves
   the host. When every address is public, it allows the connection with
   no token. When an address is internal, it allows the connection only
   when the connection comes from the address of the live pod with the
   token's pod uid, and one of these is true:
    - The token holds the host, and the port is 443.
    - Every internal address of the host is in a CIDR of the token, and
      the port is a TCP port of that CIDR.
4. TLS is end to end between the client and the host. The proxy does not
   decrypt traffic.

The network policies still block every other internal address for runner
pods. A client that does not use the proxy cannot reach a host name
destination.

Host name destinations need egress allowlists (`networkPolicy.enabled`).
Without them, the proxy adds no control.

#### Clients that use the proxy

The runner sets `HTTPS_PROXY`, `https_proxy`, `NO_PROXY`, and `no_proxy`
for these:

| Client | Uses the proxy |
|---|---|
| The agent CLI and its `Bash` tool (`curl`, `git`, `pip`, `uv`, `npm`, `gh`) | Yes |
| `run_with_secret` commands | Yes |
| The repository and plugin clones of the runner | Yes |
| Node.js `fetch` without `NODE_USE_ENV_PROXY=1` | No |
| `ssh` (for example `git` over SSH) | No |
| Database drivers and other clients that are not HTTP | No |

`NO_PROXY` holds `localhost`, `127.0.0.1`, `::1`, the imbi-api host, the
imbi-mcp host, and the CIDRs of the chain's CIDR destinations. The local
model proxy of the runner is on `127.0.0.1`.

CIDR destinations also work when the proxy is on:

- A URL with an IP literal in a CIDR of the chain (for example
  `https://10.20.1.5:8443/`) matches `NO_PROXY` and goes direct, through
  the network policy. `curl` 7.86 and later, `git`, and Python `requests`
  accept CIDRs in `NO_PROXY`.
- A URL with a host name goes through the proxy. The proxy allows it when
  the internal addresses of the name are in a CIDR of the token, on a TCP
  port of that CIDR. UDP ports are not in the token.

Public HTTPS of these clients also goes through the proxy, because
`NO_PROXY` cannot list every public host. This is a default, not a
control. A command can unset `HTTPS_PROXY` and connect to a public host
directly. It cannot connect to an internal host directly. Do not use the
proxy log as an audit of public egress.

Plain HTTP does not go through the proxy, and the proxy accepts only
`CONNECT`.

#### DNS trust

A host name allows every internal address that its DNS answer gives, on
port 443. When you add a host name, you trust the owner of its DNS zone. A
changed DNS record changes the target. If you do not trust a zone, use a
CIDR destination for it.

#### Proxy token and key rotation

The token is a JWT signed with HS256. imbi-api signs it with
`IMBI_HARNESS_EGRESS_PROXY_SECRET`. The proxy checks it with the key in
`egressProxy.secret` of the chart. Use the same value in both. This key is
not the imbi-api JWT key: do not use the same value.

The token is valid for 7 days, and only while its pod is live. The model
can read the token, because it is in the environment of its commands. The
token gives nothing that the chain does not already have, and it works only
from its own pod.

To rotate the key:

1. Put the old key in the `previous` key of the proxy Secret, and the new
   key in `current`. Restart the proxy Deployment.
2. Set `IMBI_HARNESS_EGRESS_PROXY_SECRET` of imbi-api to the new key.
   Restart imbi-api.
3. After 7 days, remove the `previous` key. Restart the proxy Deployment.

#### Turn on the proxy

1. Turn on egress allowlists first. Check that a destination becomes
   applied.
2. Make a random key and store it in a Secret in the runner namespace:

    ```sh
    kubectl create secret generic imbi-egress-proxy-key -n imbi-runners \
      --from-literal=current="$(openssl rand -base64 48)"
    ```

3. Give imbi-api the same value as `IMBI_HARNESS_EGRESS_PROXY_SECRET`. With
   the `imbi` chart, add it to `extraEnv` with a `secretKeyRef`.
4. In every harness release, set `egressProxy.enabled: true`. In the
   `manageGlobal` release, also set `egressProxy.secret.existingSecret`.
5. Upgrade the `manageGlobal` release first, then the other releases.
6. Add a host name destination for a test host. Assign it to a test agent.
   Run a task that calls `curl https://<host>/`. Run the same task with an
   agent that does not have it. The proxy refuses it with `407` when the
   agent has no egress destination (the claim has no token), and with
   `403` when the agent has other destinations.
7. Watch the proxy log and the task failures for 2 days.

#### Turn off the proxy

Set `egressProxy.enabled: false` in every release and upgrade. The runners
lose the proxy settings, so host name destinations stop working (fail
closed). CIDR destinations do not change.

#### Proxy troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `407` from the proxy (`curl: (56) CONNECT tunnel failed, response 407`) | The host is internal and the token is missing, not valid, or expired, or the connection does not come from the token's live pod. A token from another pod is refused. A chain with no egress destination (or only UDP CIDRs) gets no token | Check that imbi-api and the proxy have the same key. Check that the runner pod has `POD_UID`. A command that changed `HTTPS_PROXY` sends no token. Assign a destination to the root agent of the chain |
| `403` from the proxy | The host is internal and the chain holds neither the host name on port 443 nor a CIDR of each address with that TCP port, or the host resolves to a special address (loopback, link-local, IMDS, and others) | Assign the host name destination, or a CIDR destination with the port, to the root agent of the chain. Check the DNS answer of the host |
| `503` from the proxy | The proxy has its maximum number of tunnels (512 for each replica) | Add replicas (`egressProxy.replicas`) |
| `405` from the proxy | The client sent a plain HTTP request, not `CONNECT` | Use HTTPS |
| A connection times out | The client does not use the proxy, and the network policy drops the connection | Use a client that reads `HTTPS_PROXY` (see the table above) |
| All held hosts get `407` for a short time after a proxy start | The proxy refuses held hosts until its first pod list is done, and while its pod watch is down for more than 30 seconds | Check the proxy log and `/readyz`. Check the proxy Role |

The proxy serves `/healthz`, `/readyz`, and `/metrics` on
`egressProxy.adminPort`. Its ingress policy accepts the runner pods on the
proxy port and every pod on the admin port, so Prometheus can scrape
`/metrics`. It refuses all other ingress.

## The Agent Runners page

Open **Admin > <organization> Admin > Agent Runners**. The page lists the pools that serve the
selected organization and their runners that are not offline. It refreshes
every 15 seconds. The page is read only.

- Organization administrators need `harness_pool:read`. They see only the
  chains of their organization.
- Platform administrators see every chain of the listed pools.

| Runner state | Meaning |
|---|---|
| `idle` | Registered and waiting for work |
| `busy` | Running a chain |
| `fenced` | Its lease expired. Imbi took its chain back |
| `offline` | Gone. The page does not show it |

A chain that is not `running` shows its state:

| Chain state | Meaning |
|---|---|
| `fencing` | Imbi is ending the chain's access after a lost runner |
| `stuck` | A fencer failed. Hover over the badge for the error. The next sweep tries again |

An `exclusive` badge marks an exclusive pool.

A busy runner shows the egress destinations of its chain, with their
generations.

## Metrics

imbi-api serves these gauges at `/metrics`. Each imbi-api pod refreshes them
every 15 seconds from the database, so every pod reports the same values.
Aggregate them with `max()`.

| Metric | Labels | Value |
|---|---|---|
| `imbi_harness_pool_queued` | `pool` | Tasks that a new runner of the pool could claim now. The same number as the queue endpoint |
| `imbi_harness_runners` | `pool`, `state` | Runners that are not offline |
| `imbi_harness_chains` | `state` | Chains that are not done |
| `imbi_harness_metrics_up` | none | 1 when the last refresh worked, else 0 |

When a refresh fails or takes more than 10 seconds,
`imbi_harness_metrics_up` is 0. The other gauges then keep the values of the
last good refresh.

The runner pods do not serve metrics. See
[Kubernetes: Metrics](kubernetes.md#metrics) for the scrape setup.

## Troubleshooting

Find the error code first:

- A failed task shows the outcome `failed_external` and a reason. The
  reason is the code.
- A refused secret request shows the reason in **Admin > <organization> Admin > Secrets**, on the **Audit**
  tab.
  The runner log also shows `Refused <purpose> secret: <code>`.
- A refused API request shows the code in the response body and in the
  runner log.

### Task failure reasons

| Reason | Cause | Fix |
|---|---|---|
| `model_key_missing` | The platform configuration has no `model_upstream.key_ref` | Do [step 5](#5-configure-the-model-key) |
| `model_upstream_insecure` | The model upstream URL uses `http://` and `model_upstream.allow_insecure_http` is off. The runner does not send the key without TLS | Change the **Base URL** to `https://`. For a protected in-cluster upstream only, turn on **Allow http://**. See [step 5](#5-configure-the-model-key) |
| `model_key_refused` | The broker refused the `model_inference` request | Check the grant: the agent, the binding, the purpose `model_inference`, and the delivery mode `file_descriptor`. The binding is the agent's **Model key**, or the organization's key when the agent has none |
| `model_key_unavailable` | The executor could not get the key value | Validate the binding. Check the provider |
| `workspace_checkout_refused` | The broker refused the `workspace_checkout` token | Check the GitHub grants of [step 6](#6-configure-github-access) |
| `workspace_checkout_failed` | The clone of a project repository failed | Check that the GitHub App can read the repository |
| `marketplace_fetch_failed` | The clone of a plugin marketplace or plugin repository failed | When the binding's `repositories` is not empty, put each marketplace and external plugin repository in it. Install the App on each GitHub organization. A marketplace that is not on public github.com needs a token |
| `plugin_not_pinned` | A plugin in the configuration has no URL or commit | Save the agent again. A save pins each plugin to a commit |
| `plugin_not_loaded` | The CLI did not load a pinned plugin | Look for the `SDK init` line in the runner log. It lists the plugins that loaded |
| `service_account_in_other_organizations` | The agent's service account is a member of more than one organization, so Imbi gives it no API token | Remove the service account from the other organizations |
| `no_api_token` | The agent has Imbi tools, but Imbi gave no API token | Check the imbi-api log for the claim |
| `executor_unavailable` | The runner cannot reach the executor socket | Check the `executor` container log |
| `harness_error` | An unexpected error in the runner | Check the `runner` container log |

A task event `egress.destination_pending` means that the claim left out a
destination: `not_applied` (the sync has not made the policy of its
current generation; check that `egress-sync` runs), `organization_not_allowed`
(the destination is not for the task's organization), or `unknown` (the
destination was deleted). The task runs without it.

A task with the outcome `unhandled_no_actor` and the reason
`service_account_missing` has an agent with no service account. Imbi does
not run it.

### Secret broker reasons

| Reason | Cause | Fix |
|---|---|---|
| `repositories_span_installations` | The repositories of one token are in more than one GitHub App installation | Use repositories from one GitHub organization per task, or use separate bindings |
| `repository_not_allowed` | A `marketplace_fetch` request names a repository that is not in the binding's `repositories` | Add the repository to `repositories`, or empty the list to allow each repository of the installation |
| `setup_purpose_file_descriptor_only` | A runner purpose was requested with a mode other than `file_descriptor` | Grant `model_inference`, `workspace_checkout`, and `marketplace_fetch` with `file_descriptor` only |
| `ambiguous_grants` | More than one grant allows the request | Remove the overlap, so that exactly one grant matches |
| `no_grant` | No grant allows the request | Check the grant's agents, bindings, purposes, delivery modes, and projects |

### API errors

| Code | Cause | Fix |
|---|---|---|
| `403 pool_forbidden` | Registration: no pool has the chart's pool name, or the credential is not the pool's service account | Make `pool.name` (or the release name) match the pool in Imbi. Put the pool service account's credential in the Secret |
| `401 stale_attempt` | The agent token is for a chain attempt that is not current. Imbi fenced the chain and gave it to a new attempt | Normally no action. The runner stops. If it occurs often, check that the runners can reach imbi-api reliably |
| `409 pool_in_use` | A delete of a pool with runners that are not offline | Uninstall the release or scale it to 0, then delete the pool |
| `409 runner_label_missing` | A child task needs labels that the runner does not have | Run the child agent in a pool with its labels, or change the agent's required labels |
| `409 egress_destination_missing` | A child task's agent has an egress destination that the pod of the chain does not have | Give the root agent the destination too, or remove it from the child agent |
| `409 egress_destination_in_use` | A delete of a destination that agents have, or a change of it to global | Remove the destination from the agents first |
| `403 egress_sync_forbidden` | The egress sync's credential is not the service account of a runner pool | Use the pool credential |
| `403 agent_api_forbidden` | An agent called an Imbi route that agent tokens cannot use, or another organization | The route is refused by design. See [Agents](../admin/agents.md) |

### Other problems

- **No runner registers.** Check the `runner` container log. Check that
  `imbi.apiUrl` includes the route prefix, for example `/api`.
- **The pod does not start.** Check the namespace Pod Security level. It
  must be Baseline, not Restricted.
- **A chain stays `stuck`.** A fencer failed. The badge on the Agent Runners
  page shows the error. Imbi tries again on each sweep.
- **KEDA starts no Jobs.** Call the queue endpoint with the pool credential.
  Check that `scaledJob.apiUrl` resolves from the `keda` namespace.

The chart has no CI coverage. Check a change with `helm template` and a
server-side dry run before you install it.
