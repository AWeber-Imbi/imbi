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
  echo "--- stub log" >&2
  k logs deploy/harness-stub --tail=100 >&2 || true
}

if ! "$KIND" get clusters | grep -qx "$CLUSTER"; then
  "$KIND" create cluster --name "$CLUSTER" --config "$HERE/kind.yaml" \
    --wait 120s
fi

docker build -f "$ROOT/apps/harness/Dockerfile" --target isolation \
  -t "$IMAGE" "$ROOT"
"$KIND" load docker-image "$IMAGE" --name "$CLUSTER"

kubectl --context "$CONTEXT" delete namespace "$NAMESPACE" \
  --ignore-not-found --wait
kubectl --context "$CONTEXT" apply -f "$HERE/manifests.yaml"
trap 'status=$?; if [ $status -ne 0 ]; then dump; fi' EXIT
k rollout status deploy/harness-stub --timeout=120s
k wait --for=condition=Ready pod/harness --timeout=180s

k exec harness -c runner -- python3 -m unittest discover \
  -s /opt/isolation -p test_pod.py -v

STUB_URL=http://localhost:30080 KUBE_CONTEXT=$CONTEXT \
  "$PYTHON" -m unittest discover -s "$HERE" -p test_lifecycle.py -v

if [ "${KEEP:-0}" != 1 ]; then
  kubectl --context "$CONTEXT" delete namespace "$NAMESPACE" --wait=false
fi
