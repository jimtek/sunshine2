from fleetops import baseline, triggers


def test_no_triggers_for_inventory_matching_defaults(defaults):
    inv = {"total_gpus": 1200, "idle_reserved_gpus": 40, "active_capacity_block_instances": 60,
           "summary": [{"region": "us-east-1", "instance_type": "p5.48xlarge"}]}
    assert triggers.check(defaults, inv) == []


def test_triggers_fire_on_scale_region_and_blocks(defaults):
    inv = {"total_gpus": 2400, "idle_reserved_gpus": 600, "active_capacity_block_instances": 230,
           "summary": [{"region": "us-west-2", "instance_type": "p4d.24xlarge"}],
           "unknown_accelerated_types": {"g7.48xlarge": 2}}
    fired = "\n".join(triggers.check(defaults, inv))
    for needle in ("exceeds planned maximum", "2,048", "us-west-2", "p4d", "org limit", "idle", "g7"):
        assert needle in fired


def test_baseline_report(defaults):
    rows = baseline.evaluate(defaults["targets"], {
        "allocation_ratio": 0.62, "gpu_utilization": 0.75, "tickets_per_researcher": 2.0,
    })
    by = {r.metric: r for r in rows}
    assert by["allocation_ratio"].status == "misses"
    assert by["gpu_utilization"].status == "meets"
    assert by["tickets_per_researcher"].target == 1.0
    assert by["tickets_per_researcher"].status == "baseline-set"
    assert by["fault_to_quarantine"].status == "not-measured"
    md = baseline.to_markdown(rows)
    assert "| Allocated GPU-hours / available GPU-hours | 62% | 85% | misses |" in md
