import copy

import pytest
import yaml

from conftest import ROOT
from fleetops import platform as pf
from fleetops import render


@pytest.fixture
def pcfg():
    return pf.load(ROOT / "config" / "platform.yaml")


def test_committed_manifests_match_config(pcfg):
    assert render.drift(pcfg, ROOT) == []


def test_quotas_sum_to_pool_and_are_whole_nodes(pcfg):
    quotas = pf.team_quotas(pcfg)
    for pname, pool in pcfg["pools"].items():
        totals = pf.pool_totals(pool)
        for res, total in totals.items():
            assert sum(quotas[t][pname][res] for t in pcfg["teams"]) == total
        for t in pcfg["teams"]:
            assert quotas[t][pname]["nvidia.com/gpu"] % pool["gpus_per_node"] == 0


def test_uneven_shares_still_sum(pcfg):
    cfg = copy.deepcopy(pcfg)
    cfg["teams"] = {"a": {"share": 0.5}, "b": {"share": 0.3}, "c": {"share": 0.2}}
    assert pf.validate(cfg) == []
    nodes = pf.team_nodes(cfg, "reserved")
    assert sum(nodes.values()) == cfg["pools"]["reserved"]["nodes"]


def test_cluster_queues(pcfg):
    cqs = render.cluster_queues(pcfg)
    assert [c["metadata"]["name"] for c in cqs] == list(pcfg["teams"])
    flavors = [f["name"] for f in cqs[0]["spec"]["resourceGroups"][0]["flavors"]]
    assert flavors == ["capacity-block", "reserved", "dev"]   # expiring capacity first
    assert all(c["spec"]["cohort"] == pcfg["cohort"] for c in cqs)


def test_kwok_nodes_match_pools(pcfg):
    nodes = render.kwok_nodes(pcfg)
    assert len(nodes) == sum(p["nodes"] for p in pcfg["pools"].values())
    gpus = sum(int(n["status"]["allocatable"]["nvidia.com/gpu"]) for n in nodes)
    assert gpus == sum(p["nodes"] * p["gpus_per_node"] for p in pcfg["pools"].values())


def test_rendered_files_parse_and_have_kinds(pcfg):
    for rel, text in render.outputs(pcfg).items():
        for doc in yaml.safe_load_all(text):
            assert doc["apiVersion"] and doc["kind"], rel


def test_validation_catches_bad_shares(pcfg):
    cfg = copy.deepcopy(pcfg)
    cfg["teams"]["team-alpha"]["share"] = 0.9
    assert any("shares" in p for p in pf.validate(cfg))
