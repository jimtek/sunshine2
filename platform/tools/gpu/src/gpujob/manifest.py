"""Turn a checked JobSpec into Kubernetes objects.

One Indexed Job per training run (one pod per node) plus, for multi-node
runs, a headless Service so ranks can find rank 0. Kueue admits the whole Job
at once, so a gang either gets all its nodes or waits.
"""

from __future__ import annotations

from typing import Any

from . import platform as pf
from .preflight import Result
from .spec import JobSpec

POOL_LABEL = "platform.gpu/pool"
MASTER_PORT = 29500


def build(spec: JobSpec, result: Result, cfg: dict) -> list[dict[str, Any]]:
    if not result.ok or result.placement is None:
        raise ValueError("preflight failed; fix the errors before building manifests")
    pl = result.placement
    labels = {
        "team": spec.team,
        "project": spec.project,
        "experiment-id": spec.experiment,
        "kueue.x-k8s.io/queue-name": "default",
        "kueue.x-k8s.io/priority-class": result.priority,
        "platform.gpu/submitted-by": "gpu-cli",
    }
    pod_labels = {k: v for k, v in labels.items() if not k.startswith("kueue.x-k8s.io/")}
    resources: dict[str, Any] = {
        "cpu": str(pl.cpu), "memory": f"{pl.memory_gi}Gi", "nvidia.com/gpu": str(pl.gpus_per_node),
    }
    if pl.efa:
        resources["vpc.amazonaws.com/efa"] = str(pl.efa)

    env = [
        {"name": "NNODES", "value": str(pl.nodes)},
        {"name": "NPROC_PER_NODE", "value": str(pl.gpus_per_node)},
        {"name": "NODE_RANK", "valueFrom": {"fieldRef": {
            "fieldPath": "metadata.annotations['batch.kubernetes.io/job-completion-index']"}}},
        {"name": "MASTER_ADDR", "value": f"{spec.name}-0.{spec.name}" if pl.nodes > 1 else "localhost"},
        {"name": "MASTER_PORT", "value": str(MASTER_PORT)},
        {"name": "EXPERIMENT_ID", "value": spec.experiment},
    ]
    if spec.checkpoint_dir:
        env.append({"name": "CHECKPOINT_DIR", "value": spec.checkpoint_dir})
    if pl.efa:
        env += [{"name": "FI_PROVIDER", "value": "efa"}, {"name": "FI_EFA_USE_DEVICE_RDMA", "value": "1"}]
    env += [{"name": k, "value": str(v)} for k, v in sorted(spec.env.items())]

    pod_spec: dict[str, Any] = {
        "restartPolicy": "Never",
        "terminationGracePeriodSeconds": pf.seconds(cfg["jobs"]["termination_grace"]),
        "containers": [{
            "name": "trainer",
            "image": spec.image,
            "command": spec.command,
            "env": env,
            "resources": {"requests": resources, "limits": dict(resources)},
            "volumeMounts": [{"name": "dshm", "mountPath": "/dev/shm"}],
        }],
        "volumes": [{"name": "dshm", "emptyDir": {"medium": "Memory"}}],
    }
    if pl.nodes > 1:
        pod_spec["subdomain"] = spec.name
    if len(pl.pools) == 1:
        pod_spec["nodeSelector"] = {POOL_LABEL: pl.pools[0]}
    elif pl.avoid:
        pod_spec["affinity"] = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
            "nodeSelectorTerms": [{"matchExpressions": [
                {"key": POOL_LABEL, "operator": "In", "values": pl.pools}]}]}}}

    annotations = {"platform.gpu/max-runtime": spec.max_runtime}
    if spec.checkpoint_dir:
        annotations["platform.gpu/checkpoint-dir"] = spec.checkpoint_dir
    job = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": spec.name, "namespace": spec.team, "labels": labels, "annotations": annotations},
        "spec": {
            "suspend": True,                   # Kueue un-suspends on admission
            "completionMode": "Indexed",
            "completions": pl.nodes,
            "parallelism": pl.nodes,
            "backoffLimit": 0,                 # resume from checkpoint, don't restart blindly
            "activeDeadlineSeconds": pf.seconds(spec.max_runtime),
            "ttlSecondsAfterFinished": 7 * 86400,
            "template": {
                "metadata": {"labels": pod_labels, "annotations": dict(spec.pod_annotations)},
                "spec": pod_spec,
            },
        },
    }
    docs = [job]
    if pl.nodes > 1:
        docs.append({
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": spec.name, "namespace": spec.team, "labels": pod_labels},
            "spec": {"clusterIP": "None", "publishNotReadyAddresses": True,
                     "selector": {"job-name": spec.name}},
        })
    return docs
