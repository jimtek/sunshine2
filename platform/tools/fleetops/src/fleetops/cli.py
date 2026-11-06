"""fleetops command line: check-config, inventory, triggers, baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import baseline, config, inventory, triggers

DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "fleet-defaults.yaml"


def _load_any(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh) if path.endswith(".json") else yaml.safe_load(fh)


def cmd_check_config(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    problems = config.validate(cfg)
    for p in problems:
        print(f"ERROR {p}")
    open_items = config.open_assumptions(cfg)
    print(f"{len(open_items)} assumptions still open:")
    for name, trigger in open_items:
        print(f"  - {name}: revisit if {trigger}")
    return 1 if problems else 0


def cmd_inventory(args: argparse.Namespace) -> int:
    accts = _load_any(args.accounts)
    factory = inventory.assume_role_factory(accts.get("role_name", "FleetInventoryReadOnly"))
    inv = inventory.collect(accts["accounts"], args.region or accts.get("regions", ["us-east-1"]), factory)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(inv.to_json())
    (out / "inventory-summary.csv").write_text(inv.summary_csv())
    print(f"{inv.total_gpus} GPUs on {len(inv.instances)} instances; "
          f"{len(inv.reservations)} reservations; {len(inv.errors)} errors -> {out}")
    for e in inv.errors:
        print(f"WARN {e}", file=sys.stderr)
    return 0 if not inv.errors else 2


def cmd_triggers(args: argparse.Namespace) -> int:
    fired = triggers.check(config.load(args.config), _load_any(args.inventory))
    for f in fired:
        print(f"REVISIT {f}")
    if not fired:
        print("No revisit triggers fired; defaults hold for this inventory.")
    return 3 if fired else 0


def cmd_baseline(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    rows = baseline.evaluate(cfg["targets"], _load_any(args.measurements) or {})
    md = baseline.to_markdown(rows)
    if args.out:
        Path(args.out).write_text(md)
    else:
        print(md, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fleetops", description=__doc__)
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="fleet-defaults.yaml path")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("check-config", help="validate defaults and list open assumptions")
    s.set_defaults(fn=cmd_check_config)

    s = sub.add_parser("inventory", help="collect GPU inventory across accounts (read-only)")
    s.add_argument("--accounts", required=True, help="accounts.yaml (see config/accounts.example.yaml)")
    s.add_argument("--region", action="append", help="override regions; repeatable")
    s.add_argument("--out-dir", default="out")
    s.set_defaults(fn=cmd_inventory)

    s = sub.add_parser("triggers", help="check an inventory.json against revisit_if triggers")
    s.add_argument("--inventory", required=True)
    s.set_defaults(fn=cmd_triggers)

    s = sub.add_parser("baseline", help="render baseline vs. targets as markdown")
    s.add_argument("--measurements", required=True, help="YAML/JSON of measured values")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_baseline)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
