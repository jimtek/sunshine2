from datetime import timedelta

import pytest

from conftest import NOW
from gpujob import preflight
from gpujob.spec import JobSpec


def codes(result, level="error"):
    return {f.code for f in result.findings if f.level == level}


def test_good_multi_node_job_places_on_big_pools(cfg, spec):
    r = preflight.run(spec(), cfg, NOW)
    assert r.ok, r.findings
    assert r.placement.pools == ["capacity-block", "reserved"]
    assert (r.placement.nodes, r.placement.gpus_per_node) == (2, 8)
    assert r.placement.efa == 16          # min across pools
    assert r.priority == "standard"


def test_single_gpu_goes_to_dev_without_checkpoint(cfg, spec):
    r = preflight.run(spec(gpus=1, max_runtime="2h", checkpoint_dir=None), cfg, NOW)
    assert r.ok, r.findings
    assert r.placement.pools == ["dev"]
    assert r.placement.efa == 0


def test_partial_node_job_shares_one_big_node(cfg, spec):
    r = preflight.run(spec(gpus=4), cfg, NOW)
    assert r.ok, r.findings
    assert r.placement.pools == ["capacity-block", "reserved"]
    assert (r.placement.nodes, r.placement.gpus_per_node, r.placement.efa) == (1, 4, 0)
    assert r.placement.cpu == 188 // 2


@pytest.mark.parametrize("gpus,code", [(12, "TOPOLOGY"), (200, "TOPOLOGY"), (0, "TOPOLOGY")])
def test_topology_errors(cfg, spec, gpus, code):
    assert code in codes(preflight.run(spec(gpus=gpus), cfg, NOW))


def test_dev_pool_runtime_cap(cfg, spec):
    assert "RUNTIME" in codes(preflight.run(spec(gpus=1, max_runtime="10h", pool="dev"), cfg, NOW))
    long_single = preflight.run(spec(gpus=1, max_runtime="10h"), cfg, NOW)
    assert long_single.ok and long_single.placement.pools == ["capacity-block", "reserved"]


def test_long_job_needs_checkpoint(cfg, spec):
    assert "CHECKPOINT" in codes(preflight.run(spec(checkpoint_dir=None), cfg, NOW))
    assert "CHECKPOINT" in codes(preflight.run(spec(checkpoint_dir="/home/me/ckpt"), cfg, NOW))


def test_preemptible_needs_resume_test(cfg, spec):
    assert "PREEMPT" in codes(preflight.run(spec(priority="preemptible"), cfg, NOW))
    assert preflight.run(spec(priority="preemptible", resume_tested=True), cfg, NOW).ok


def test_image_rules(cfg, spec):
    assert "IMAGE" in codes(preflight.run(spec(image="docker.io/me/train:v1"), cfg, NOW))
    assert "IMAGE" in codes(preflight.run(spec(image="nvcr.io/nvidia/pytorch:latest"), cfg, NOW))
    ecr = "123456789012.dkr.ecr.us-east-1.amazonaws.com/train:2026-11-01-cuda12.4"
    assert preflight.run(spec(image=ecr), cfg, NOW).ok


def test_driver_mismatch(cfg, spec):
    r = preflight.run(spec(image="nvcr.io/nvidia/pytorch:25.06-py3"), cfg, NOW)
    assert "DRIVER" in codes(r)        # CUDA 12.9 > driver max 12.8
    r = preflight.run(spec(image="public.ecr.aws/me/train:v3"), cfg, NOW)
    assert "DRIVER" in codes(r, "warn")


def test_data_paths(cfg, spec):
    assert "DATA" in codes(preflight.run(spec(data=["/home/me/data"]), cfg, NOW))
    assert preflight.run(spec(data=["s3://b/d", "/fsx/datasets/x"]), cfg, NOW).ok


def test_quota_borrow_warning(cfg, spec):
    r = preflight.run(spec(gpus=64), cfg, NOW)
    assert r.ok and "QUOTA" in codes(r, "warn")


def test_capacity_block_expiry_avoids_the_block(cfg, spec):
    from datetime import datetime
    ends = datetime.fromisoformat(cfg["pools"]["capacity-block"]["ends_at"].replace("Z", "+00:00"))
    near_end = ends - timedelta(hours=8)        # 6h left before the 2h drain
    r = preflight.run(spec(max_runtime="12h"), cfg, near_end)
    assert r.ok and r.placement.pools == ["reserved"] and r.placement.avoid == ["capacity-block"]
    assert "CAPACITY" in codes(r, "warn")
    pinned = preflight.run(spec(max_runtime="12h", pool="capacity-block"), cfg, near_end)
    assert "CAPACITY" in codes(pinned)
    assert preflight.run(spec(max_runtime="4h", pool="capacity-block"), cfg, near_end).ok


def test_identity_checks(cfg, spec):
    assert "NAME" in codes(preflight.run(spec(name="Bad_Name"), cfg, NOW))
    assert "TEAM" in codes(preflight.run(spec(team="team-zeta"), cfg, NOW))
    assert "LABELS" in codes(preflight.run(spec(experiment="has spaces"), cfg, NOW))
    assert "PRIORITY" in codes(preflight.run(spec(priority="urgent"), cfg, NOW))
    assert "RUNTIME" in codes(preflight.run(spec(max_runtime="100h"), cfg, NOW))


def test_spec_rejects_unknown_and_missing_fields():
    with pytest.raises(ValueError, match="unknown"):
        JobSpec.from_dict({"name": "x", "gpuz": 1})
    with pytest.raises(ValueError, match="missing"):
        JobSpec.from_dict({"name": "x"})
