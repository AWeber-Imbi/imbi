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

The chart has no CI coverage. Check a change with `helm template` and a dry run
against a cluster.
