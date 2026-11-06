#!/usr/bin/env bash
# Bring up the Phase 1 simulation: kind + Kueue + KWOK fake GPU nodes.
# Requires docker, kind and kubectl on PATH. Idempotent.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
source "$here/versions.env"
kueue_version="$(awk '/^kueue_version:/ {print $2}' "$root/config/platform.yaml")"

if ! kind get clusters | grep -qx gpu-sim; then
  kind create cluster --config "$here/kind-config.yaml" --wait 120s
fi
kubectl config use-context kind-gpu-sim >/dev/null

echo "Installing KWOK ${KWOK_VERSION}"
kubectl apply -f "https://github.com/kubernetes-sigs/kwok/releases/download/${KWOK_VERSION}/kwok.yaml"
kubectl apply -f "https://github.com/kubernetes-sigs/kwok/releases/download/${KWOK_VERSION}/stage-fast.yaml"
# Keep fake pods running until the replay deletes their job; don't auto-complete them.
kubectl delete stage pod-complete --ignore-not-found
kubectl -n kube-system rollout status deployment/kwok-controller --timeout=120s

echo "Installing Kueue ${kueue_version}"
kubectl apply --server-side -f "https://github.com/kubernetes-sigs/kueue/releases/download/${kueue_version}/manifests.yaml"
kubectl apply -f "$root/cluster/kueue-system/controller-config.yaml"
kubectl -n kueue-system rollout restart deployment/kueue-controller-manager
kubectl -n kueue-system rollout status deployment/kueue-controller-manager --timeout=180s

echo "Adding fake GPU nodes"
kubectl apply -f "$here/kwok-nodes.yaml"

echo "Applying platform objects"
# Webhooks can take a few seconds after rollout; retry briefly.
for i in 1 2 3 4 5 6; do
  kubectl apply -k "$root/cluster" && break
  echo "retrying in 10s ($i)"; sleep 10
done

kubectl get nodes -l type=kwok --no-headers | wc -l | xargs echo "fake GPU nodes:"
kubectl get clusterqueues
