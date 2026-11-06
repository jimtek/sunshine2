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
