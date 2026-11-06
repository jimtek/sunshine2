import copy

from fleetops import config


def test_committed_defaults_are_valid(defaults):
    assert config.validate(defaults) == []


def test_every_assumed_section_is_open(defaults):
    names = {n for n, _ in config.open_assumptions(defaults)}
    assert {"fleet", "workload_mix", "checkpointing", "staffing"} <= names


def test_bad_status_and_missing_trigger_are_reported(defaults):
    cfg = copy.deepcopy(defaults)
    cfg["fleet"]["status"] = "guessed"
    del cfg["checkpointing"]["revisit_if"]
    problems = config.validate(cfg)
    assert any("fleet.status" in p for p in problems)
    assert any("checkpointing" in p for p in problems)
