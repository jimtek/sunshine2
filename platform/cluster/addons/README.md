# Cluster add-ons (installed on EKS, not in the simulation)

Pinned versions; upgrade on the pilot pool first.

| Add-on | Chart | Version | Values |
|---|---|---|---|
| NVIDIA GPU Operator | `nvidia/gpu-operator` | v24.9.2 | `gpu-operator-values.yaml` |
| EFA device plugin | `eks/aws-efa-k8s-device-plugin` | v0.5.6 | `efa-device-plugin-values.yaml` |
| kube-prometheus-stack | `prometheus-community/kube-prometheus-stack` | 66.3.1 | `kube-prometheus-stack-values.yaml` |
| Kueue | release manifest | from `config/platform.yaml` | `../kueue-system/controller-config.yaml` |

Chart versions were set at scaffold time and not yet installed anywhere;
confirm each exists and passes on the week-9 smoke test before relying on it.

```bash
helm upgrade --install gpu-operator nvidia/gpu-operator -n gpu-operator --create-namespace \
  --version v24.9.2 -f gpu-operator-values.yaml
helm upgrade --install efa eks/aws-efa-k8s-device-plugin -n kube-system \
  --version v0.5.6 -f efa-device-plugin-values.yaml
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack -n monitoring \
  --create-namespace --version 66.3.1 -f kube-prometheus-stack-values.yaml
kubectl apply -f ../../observability/prometheus-rules.yaml
```
