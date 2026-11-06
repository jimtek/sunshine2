"""gpu: submit, watch and cancel GPU jobs on the fleet platform.

  gpu preflight job.yaml          check a job without submitting it
  gpu submit job.yaml [--dry-run] check, then submit (or print the manifests)
  gpu status --team T [NAME]      queued / running / finished jobs
  gpu logs NAME --team T [--rank N] [-f]
  gpu cancel NAME --team T
  gpu replay trace.csv            (platform team) replay a trace on the sim cluster
  gpu trace --jobs 300 > t.csv    (platform team) generate a synthetic trace
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

from . import manifest, platform, preflight, replay
from .kube import KubeError, Kubectl
from .spec import JobSpec


def _team(args) -> str:
    team = args.team or os.environ.get("GPU_TEAM")
    if not team:
        sys.exit("error: pass --team or set GPU_TEAM")
    return team


def _check(args, cfg) -> tuple[JobSpec, preflight.Result]:
    try:
        spec = JobSpec.load(args.spec)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        sys.exit(f"error: {exc}")
    result = preflight.run(spec, cfg)
    for f in result.findings:
        print(f, file=sys.stderr)
    if result.ok and result.placement:
        p = result.placement
        print(f"OK    {spec.name}: {spec.gpus} GPUs as {p.nodes} x {p.gpus_per_node} "
              f"in {'/'.join(p.pools)}, priority {result.priority}", file=sys.stderr)
    return spec, result


def cmd_preflight(args, cfg) -> int:
    _, result = _check(args, cfg)
    return 0 if result.ok else 1


def cmd_submit(args, cfg) -> int:
    spec, result = _check(args, cfg)
    if not result.ok:
        print("Not submitted: fix the errors above.", file=sys.stderr)
        return 1
    docs = manifest.build(spec, result, cfg)
    if args.dry_run:
        print(yaml.safe_dump_all(docs, sort_keys=False), end="")
        return 0
    try:
        Kubectl(args.context).apply(docs)
    except KubeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Submitted {spec.name} to {spec.team}. Watch it with: gpu status --team {spec.team} {spec.name}")
    return 0


def _job_state(job: dict, wl: dict | None) -> str:
    st = job.get("status", {})
    for c in st.get("conditions", []):
        if c["type"] == "Complete" and c["status"] == "True":
            return "succeeded"
        if c["type"] == "Failed" and c["status"] == "True":
            return f"failed ({c.get('reason', '')})"
    conds = {c["type"]: c for c in (wl or {}).get("status", {}).get("conditions", [])}
    if conds.get("Evicted", {}).get("status") == "True" and conds.get("Admitted", {}).get("status") != "True":
        return f"requeued ({conds['Evicted'].get('reason', '')})"
    if conds.get("Admitted", {}).get("status") == "True":
        return "running" if st.get("active") else "starting"
    qr = conds.get("QuotaReserved", {})
    return f"queued: {qr.get('message', '')}".strip(": ") if qr else "queued"


def cmd_status(args, cfg) -> int:
    team = _team(args)
    kube = Kubectl(args.context)
    try:
        jobs = kube.get_json(["jobs", "-n", team, "-l", "platform.gpu/submitted-by=gpu-cli"])["items"]
        wls = kube.get_json(["workloads.kueue.x-k8s.io", "-n", team])["items"]
    except KubeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    by_job = {ref["name"]: wl for wl in wls for ref in wl["metadata"].get("ownerReferences", [])
              if ref.get("kind") == "Job"}
    rows = []
    for job in jobs:
        name = job["metadata"]["name"]
        if args.name and name != args.name:
            continue
        lab = job["metadata"].get("labels", {})
        gpus = sum(int(c["resources"]["requests"].get("nvidia.com/gpu", 0))
                   for c in job["spec"]["template"]["spec"]["containers"]) * job["spec"].get("parallelism", 1)
        rows.append((name, lab.get("experiment-id", ""), str(gpus),
                     lab.get("kueue.x-k8s.io/priority-class", ""), _job_state(job, by_job.get(name))))
    if args.json:
        print(json.dumps([dict(zip(["name", "experiment", "gpus", "priority", "state"], r)) for r in rows], indent=2))
        return 0
    if not rows:
        print("No jobs." if not args.name else f"No job named {args.name} in {team}.")
        return 0 if not args.name else 1
    header = ("NAME", "EXPERIMENT", "GPUS", "PRIORITY", "STATE")
    widths = [max(len(r[i]) for r in rows + [header]) for i in range(5)]
    for r in [header] + rows:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip())
    return 0


def cmd_logs(args, cfg) -> int:
    team = _team(args)
    selector = f"job-name={args.name},batch.kubernetes.io/job-completion-index={args.rank}"
    cmd = ["logs", "-n", team, "-l", selector, "-c", "trainer", "--tail", str(args.tail)]
    if args.follow:
        cmd.append("-f")
    try:
        Kubectl(args.context).passthrough(cmd)
    except KubeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_cancel(args, cfg) -> int:
    team = _team(args)
    kube = Kubectl(args.context)
    try:
        kube.delete("job", args.name, team)
        kube.delete("service", args.name, team)
    except KubeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Cancelled {args.name}. Its quota is released once its pods stop.")
    return 0


def cmd_trace(args, cfg) -> int:
    jobs = replay.synthetic(cfg, jobs=args.jobs, days=args.days, seed=args.seed)
    sys.stdout.write(replay.write_trace(jobs))
    return 0


def cmd_replay(args, cfg) -> int:
    with open(args.trace) as fh:
        jobs = replay.read_trace(fh.read())
    report = replay.run(Kubectl(args.context), cfg, jobs, speed=args.speed, poll_s=args.poll)
    print(json.dumps(report, indent=2))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=2)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gpu", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--platform", help="platform.yaml (default: $GPU_PLATFORM_CONFIG or the repo copy)")
    p.add_argument("--context", help="kubeconfig context")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("preflight", help="check a job spec without submitting")
    s.add_argument("spec")
    s.set_defaults(fn=cmd_preflight)

    s = sub.add_parser("submit", help="check and submit a job spec")
    s.add_argument("spec")
    s.add_argument("--dry-run", action="store_true", help="print manifests instead of submitting")
    s.set_defaults(fn=cmd_submit)

    s = sub.add_parser("status", help="list your team's jobs")
    s.add_argument("name", nargs="?")
    s.add_argument("--team")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("logs", help="show a job's logs")
    s.add_argument("name")
    s.add_argument("--team")
    s.add_argument("--rank", type=int, default=0)
    s.add_argument("--tail", type=int, default=200)
    s.add_argument("-f", "--follow", action="store_true")
    s.set_defaults(fn=cmd_logs)

    s = sub.add_parser("cancel", help="cancel a job")
    s.add_argument("name")
    s.add_argument("--team")
    s.set_defaults(fn=cmd_cancel)

    s = sub.add_parser("trace", help="(platform team) generate a synthetic trace CSV")
    s.add_argument("--jobs", type=int, default=300)
    s.add_argument("--days", type=float, default=7)
    s.add_argument("--seed", type=int, default=1)
    s.set_defaults(fn=cmd_trace)

    s = sub.add_parser("replay", help="(platform team) replay a trace on the sim cluster")
    s.add_argument("trace")
    s.add_argument("--speed", type=float, default=600, help="simulated seconds per real second")
    s.add_argument("--poll", type=float, default=5, help="real seconds between polls")
    s.add_argument("--out", help="write the JSON report here too")
    s.set_defaults(fn=cmd_replay)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = platform.load(args.platform)
    return args.fn(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
