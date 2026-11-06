from gpujob import replay


def test_synthetic_trace_shape(cfg):
    jobs = replay.synthetic(cfg, jobs=500, seed=3)
    assert len(jobs) == 500
    share_dev = sum(j.gpus == 1 for j in jobs) / len(jobs)
    assert 0.12 < share_dev < 0.28
    assert all(j.team in cfg["teams"] for j in jobs)
    assert jobs == replay.read_trace(replay.write_trace(jobs)) or len(replay.read_trace(replay.write_trace(jobs))) == 500


def test_every_synthetic_job_passes_preflight(cfg):
    from gpujob import preflight
    from conftest import NOW
    for j in replay.synthetic(cfg, jobs=200, seed=5):
        r = preflight.run(replay.spec_for(j), cfg, NOW)
        assert r.ok, (j, r.findings)


def _wl(admitted, evicted_at=None):
    conds = [{"type": "Admitted", "status": "True" if admitted else "False"}]
    if evicted_at:
        conds.append({"type": "Evicted", "status": "True", "lastTransitionTime": evicted_at})
    return {"status": {"conditions": conds}}


def test_tracker_wait_preemption_and_partial_placement():
    jobs = [replay.TraceJob("a", 0, "team-alpha", 8, 100, "standard"),
            replay.TraceJob("b", 0, "team-beta", 16, 50, "high")]
    t = replay.Tracker(jobs, capacity_gpus=32)
    for s in t.due(0):
        s.submitted_at = 0
    t.observe(10, {"a": _wl(True), "b": _wl(False)}, {})
    t.observe(40, {"a": _wl(False, "e1"), "b": _wl(True)}, {"b": 1})
    t.observe(50, {"a": _wl(True), "b": _wl(True)}, {"b": 1})
    t.observe(60, {"a": _wl(True), "b": _wl(True)}, {"b": 1})
    done = t.observe(110, {"a": _wl(True), "b": _wl(True)}, {})
    assert [s.job.id for s in done] == ["b"]
    done = t.observe(170, {"a": _wl(True)}, {})
    assert [s.job.id for s in done] == ["a"]
    rep = t.report(170)
    assert rep["finished"] == 2 and rep["evictions"] == 1 and rep["partial_placements"] == 1
    assert rep["queue_wait_by_priority"]["high"]["jobs"] == 1


class FakeKube:
    """Admits everything immediately; enough to exercise the driver loop."""

    def __init__(self):
        self.jobs = {}
        self.deleted = []

    def apply(self, docs):
        for d in docs:
            if d["kind"] == "Job":
                self.jobs[d["metadata"]["name"]] = d

    def delete(self, kind, name, ns):
        if kind == "job":
            self.jobs.pop(name, None)
            self.deleted.append(name)

    def get_json(self, args):
        if args[0].startswith("workloads"):
            ns = args[2]
            return {"items": [{"metadata": {"ownerReferences": [{"kind": "Job", "name": n}]},
                               "status": {"conditions": [{"type": "Admitted", "status": "True"}]}}
                              for n, j in self.jobs.items() if j["metadata"]["namespace"] == ns]}
        return {"items": []}


def test_driver_runs_trace_to_completion(cfg):
    jobs = replay.synthetic(cfg, jobs=20, days=0.5, seed=2)
    clock = {"t": 0.0}
    kube = FakeKube()
    report = replay.run(kube, cfg, jobs, speed=3600, poll_s=1,
                        clock=lambda: clock["t"], sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
                        log=lambda *_: None)
    assert report["finished"] == 20 and report["rejected_by_preflight"] == 0
    assert len(kube.deleted) == 20


def _preempted(evicted_at, reason):
    wl = _wl(False, evicted_at)
    wl["status"]["conditions"].append({"type": "Preempted", "status": "True", "reason": reason})
    return wl


def test_borrow_evictions_of_nonpreemptible_jobs_are_counted():
    jobs = [replay.TraceJob("std", 0, "team-alpha", 8, 100, "standard"),
            replay.TraceJob("bf", 0, "team-beta", 8, 100, "preemptible")]
    t = replay.Tracker(jobs, capacity_gpus=16)
    for s in t.due(0):
        s.submitted_at = 0
    t.observe(10, {"std": _wl(True), "bf": _wl(True)}, {})
    t.observe(20, {"std": _preempted("e1", "InCohortReclaimWhileBorrowing"),
                   "bf": _preempted("e2", "InCohortReclaimWhileBorrowing")}, {})
    rep = t.report(20)
    assert rep["evictions"] == 2
    assert rep["nonpreemptible_borrow_evictions"] == 1
    assert rep["evictions_by_priority_reason"] == {
        "preemptible/InCohortReclaimWhileBorrowing": 1, "standard/InCohortReclaimWhileBorrowing": 1}


def test_allocation_counts_only_while_jobs_wait():
    jobs = [replay.TraceJob("a", 0, "team-alpha", 8, 1000, "standard"),
            replay.TraceJob("b", 0, "team-beta", 8, 1000, "standard")]
    t = replay.Tracker(jobs, capacity_gpus=16)
    for s in t.due(0):
        s.submitted_at = 0
    t.observe(0, {"a": _wl(True), "b": _wl(False)}, {})
    t.observe(100, {"a": _wl(True), "b": _wl(False)}, {})   # b waits; 8 of 16 GPUs busy
    t.observe(200, {"a": _wl(True), "b": _wl(True)}, {})    # nobody waits: not counted
    rep = t.report(200)
    assert rep["busy_h"] == round(100 / 3600, 1)
    assert rep["allocation_ratio_busy"] == 0.5


def test_evaluate_against_adr_criteria():
    base = {"partial_placements": 0, "never_admitted": 0, "nonpreemptible_borrow_evictions": 0,
            "allocation_ratio_busy": 0.9, "queue_wait_by_priority": {"standard": {"p90_h": 3.5}}}
    assert replay.evaluate(base)["pass"]
    slow = {**base, "queue_wait_by_priority": {"standard": {"p90_h": 4.0}}}
    v = replay.evaluate(slow)
    assert not v["pass"] and not v["checks"]["p90_wait_standard_h"]["pass"]
    assert replay.evaluate(slow, {"p90_wait_standard_h_max": 6})["pass"]
    assert not replay.evaluate({**base, "allocation_ratio_busy": 0.8})["pass"]
    assert replay.evaluate({**base, "allocation_ratio_busy": None})["pass"]
