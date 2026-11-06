import re
from pathlib import Path

import pytest
import yaml

from conftest import NOW, ROOT
from gpujob import manifest, preflight


def build(cfg, spec, **kw):
    s = spec(**kw)
    return manifest.build(s, preflight.run(s, cfg, NOW), cfg)


def test_multi_node_job_and_service(cfg, spec):
    job, svc = build(cfg, spec)
    labels = job["metadata"]["labels"]
    assert labels["kueue.x-k8s.io/queue-name"] == "default"
    assert {labels[k] for k in ("team", "project", "experiment-id")} == {"team-alpha", "llm", "exp-1"}
    assert job["spec"]["suspend"] is True
    assert job["spec"]["completions"] == job["spec"]["parallelism"] == 2
    assert job["spec"]["activeDeadlineSeconds"] == 12 * 3600
    pod = job["spec"]["template"]["spec"]
    res = pod["containers"][0]["resources"]["requests"]
    assert res["nvidia.com/gpu"] == "8" and res["vpc.amazonaws.com/efa"] == "16"
    env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
    assert env["MASTER_ADDR"] == "train-a-0.train-a" and env["NNODES"] == "2"
    assert pod["subdomain"] == "train-a" and "nodeSelector" not in pod
    assert svc["spec"]["clusterIP"] == "None"


def test_single_pool_uses_node_selector(cfg, spec):
    (job,) = build(cfg, spec, gpus=1, max_runtime="2h", checkpoint_dir=None)
    pod = job["spec"]["template"]["spec"]
    assert pod["nodeSelector"] == {"platform.gpu/pool": "dev"}
    assert "vpc.amazonaws.com/efa" not in pod["containers"][0]["resources"]["requests"]


def test_refuses_failed_preflight(cfg, spec):
    s = spec(gpus=12)
    with pytest.raises(ValueError):
        manifest.build(s, preflight.run(s, cfg, NOW), cfg)


def test_job_fits_team_quota_in_rendered_cluster_queue(cfg, spec):
    """The resources we request must fit what fleetops rendered for Kueue."""
    (job, _) = build(cfg, spec, gpus=32)
    req = job["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]
    nodes = job["spec"]["parallelism"]
    cqs = list(yaml.safe_load_all((ROOT / "cluster/kueue/cluster-queues.yaml").read_text()))
    alpha = next(c for c in cqs if c["metadata"]["name"] == "team-alpha")
    reserved = next(f for f in alpha["spec"]["resourceGroups"][0]["flavors"] if f["name"] == "reserved")
    quota = {r["name"]: r["nominalQuota"] for r in reserved["resources"]}
    assert int(req["nvidia.com/gpu"]) * nodes <= quota["nvidia.com/gpu"]
    assert int(req["cpu"]) * nodes <= quota["cpu"]
    assert int(req["memory"].rstrip("Gi")) * nodes <= int(str(quota["memory"]).rstrip("Gi"))


def test_admission_policy_requires_the_configured_labels(cfg):
    policy = next(yaml.safe_load_all((ROOT / "cluster/policy/require-job-labels.yaml").read_text()))
    expr = policy["spec"]["validations"][0]["expression"]
    listed = re.findall(r"'([a-z-]+)'", expr.split(".all(")[0])
    assert listed == cfg["required_labels"]
