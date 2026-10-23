#!/bin/sh
# Run the P5a isolation suites in a kind cluster.
#
#   apps/harness/isolation/run-kind.sh
#
# KIND (default: kind) is the kind binary. CLUSTER (default: imbi-harness)
# is made when it does not exist. PYTHON (default: python3, 3.9 or later)
# runs the host suite. Set KEEP=1 to keep the namespace after the run.
set -eu

KIND=${KIND:-kind}
CLUSTER=${CLUSTER:-imbi-harness}
PYTHON=${PYTHON:-python3}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
IMAGE=imbi-harness:isolation
CONTEXT=kind-$CLUSTER
NAMESPACE=imbi-harness-test

k() {
  kubectl --context "$CONTEXT" -n "$NAMESPACE" "$@"
}

dump() {
  echo "--- pod" >&2
  k describe pod harness >&2 || true
  for c in runner executor; do
    echo "--- $c log" >&2
    k logs harness -c "$c" --tail=200 >&2 || true
    echo "--- $c previous log" >&2
    k logs harness -c "$c" --previous --tail=200 >&2 || true
  done
  for c in runner executor; do
    echo "--- pool $c logs" >&2
    k logs -l imbi.aweber.com/pool=general -c "$c" --prefix --tail=200 >&2 || true
  done
  echo "--- fake API log" >&2
  k logs deploy/harness-fake-api --tail=100 >&2 || true
  echo "--- egress-sync log" >&2
  k logs deploy/imbi-harness-egress-sync --tail=100 >&2 || true
}

if ! "$KIND" get clusters | grep -qx "$CLUSTER"; then
  "$KIND" create cluster --name "$CLUSTER" --config "$HERE/kind.yaml" \
    --wait 120s
fi
# kind has no VPC CNI: only the API type of ClusterNetworkPolicy, for the
# egress admission policies and egress-sync (test_egress.py).
kubectl --context "$CONTEXT" apply -f "$HERE/clusternetworkpolicy-crd.yaml"
kubectl --context "$CONTEXT" wait --for=condition=Established \
  crd/clusternetworkpolicies.networking.k8s.aws --timeout=60s

docker build -f "$ROOT/apps/harness/Dockerfile" --target isolation \
  -t "$IMAGE" "$ROOT"
"$KIND" load docker-image "$IMAGE" --name "$CLUSTER"

kubectl --context "$CONTEXT" delete namespace "$NAMESPACE" \
  --ignore-not-found --wait
kubectl --context "$CONTEXT" apply -f "$HERE/manifests.yaml"
trap 'status=$?; if [ $status -ne 0 ]; then dump; fi' EXIT
k rollout status deploy/harness-fake-api --timeout=120s
k wait --for=jsonpath='{.subsets[0].addresses[0].ip}' \
  endpoints/harness-fake-api --timeout=120s
k wait --for=condition=Ready pod/harness --timeout=180s
# Both suites also wait until the fake API answers from where they run
# and a runner polls for a claim (setUpModule).

k exec harness -c runner -- python3 -m unittest discover \
  -s /opt/isolation -p test_pod.py -v

FAKE_API_URL=http://localhost:30080 KUBE_CONTEXT=$CONTEXT \
  "$PYTHON" -m unittest discover -s "$HERE" -p test_lifecycle.py -v

# The pool suite: the test pod goes, and a one-pod pool from the Helm
# chart takes its place (pod self-deletion and the failure paths). The
# release also renders the egress objects (test_egress.py). It has
# cluster-scoped objects: delete them after the run.
k delete pod harness --wait
POOL=$(mktemp)
helm template general "$ROOT/helm/imbi-harness" --namespace "$NAMESPACE" \
  --set image.repository=imbi-harness --set image.tag=isolation \
  --set image.pullPolicy=Never \
  --set imbi.apiUrl=http://harness-fake-api:8080 \
  --set imbi.mcpUrl=http://harness-fake-api:8080/mcp \
  --set poolCredential.existingSecret=harness-pool \
  --set networkPolicy.enabled=true \
  --set networkPolicy.manageGlobal=true \
  --set networkPolicy.canary=harness-fake-api:9 \
  --set networkPolicy.required.imbiApi.namespace="$NAMESPACE" \
  --set networkPolicy.required.imbiApi.podSelector.app=harness-fake-api \
  --set networkPolicy.required.imbiApi.port=8080 \
  --set networkPolicy.required.imbiMcp.namespace="$NAMESPACE" \
  --set networkPolicy.required.imbiMcp.podSelector.app=harness-fake-api \
  --set networkPolicy.required.imbiMcp.port=8080 \
  --set networkPolicy.required.kubeApi.cidr=10.96.0.1/32 \
  > "$POOL"
k apply -f "$POOL"
# Nothing enforces the policies in kind, and the CI host's IMDS answers:
# the startup self-test cannot pass. The runner runs without enforcement;
# the Role, token, and admission policies stay.
k set env deploy/general -c runner IMBI_HARNESS_EGRESS_ENFORCED=false
k rollout status deploy/general --timeout=180s
k rollout status deploy/imbi-harness-egress-sync --timeout=120s
FAKE_API_URL=http://localhost:30080 KUBE_CONTEXT=$CONTEXT \
  "$PYTHON" -m unittest discover -s "$HERE" -p test_egress.py -v
FAKE_API_URL=http://localhost:30080 KUBE_CONTEXT=$CONTEXT \
  "$PYTHON" -m unittest discover -s "$HERE" -p test_pool.py -v

if [ "${KEEP:-0}" != 1 ]; then
  k delete -f "$POOL" --ignore-not-found --wait=false
  kubectl --context "$CONTEXT" delete clusternetworkpolicies \
    -l app.kubernetes.io/managed-by=imbi-harness-egress-sync
  kubectl --context "$CONTEXT" delete namespace "$NAMESPACE" --wait=false
fi
rm -f "$POOL"
