"""Fleet inventory: GPU instances and capacity reservations across accounts.

Read-only. For each account and region it lists GPU instances and capacity
reservations (including Capacity Blocks), then aggregates by account, region,
instance type and capacity type. This is Phase 0 deliverable #1.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from . import gpus

ClientFactory = Callable[[str, str], Any]  # (account_id, region) -> EC2 client

LIVE_STATES = ["pending", "running", "stopping", "stopped"]


@dataclass
class Instance:
    account: str
    region: str
    instance_id: str
    instance_type: str
    az: str
    state: str
    capacity_type: str
    reservation_id: str | None
    gpus: int


@dataclass
class Reservation:
    account: str
    region: str
    reservation_id: str
    instance_type: str
    az: str
    kind: str                # capacity-block | odcr
    state: str
    total_instances: int
    available_instances: int
    gpus_total: int
    start: str | None
    end: str | None


@dataclass
class Inventory:
    collected_at: str
    instances: list[Instance] = field(default_factory=list)
    reservations: list[Reservation] = field(default_factory=list)
    unknown_accelerated_types: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def total_gpus(self) -> int:
        return sum(i.gpus for i in self.instances)

    def summary(self) -> list[dict[str, Any]]:
        """GPUs grouped by account, region, instance type and capacity type."""
        groups: dict[tuple, dict[str, Any]] = defaultdict(lambda: {"instances": 0, "gpus": 0})
        for i in self.instances:
            key = (i.account, i.region, i.instance_type, i.capacity_type)
            groups[key]["instances"] += 1
            groups[key]["gpus"] += i.gpus
        rows = []
        for (account, region, itype, ctype), v in sorted(groups.items()):
            rows.append({
                "account": account, "region": region, "instance_type": itype,
                "gpu_model": gpus.gpu_model(itype), "capacity_type": ctype, **v,
            })
        return rows

    def active_capacity_blocks(self) -> int:
        """Instances held in active or scheduled Capacity Blocks (org-wide limit applies)."""
        return sum(
            r.total_instances for r in self.reservations
            if r.kind == "capacity-block" and r.state in ("active", "scheduled", "payment-pending")
        )

    def idle_reserved_gpus(self) -> int:
        return sum(
            r.available_instances * (r.gpus_total // max(r.total_instances, 1))
            for r in self.reservations if r.state == "active"
        )

    def to_json(self) -> str:
        return json.dumps({
            "collected_at": self.collected_at,
            "total_gpus": self.total_gpus,
            "idle_reserved_gpus": self.idle_reserved_gpus(),
            "active_capacity_block_instances": self.active_capacity_blocks(),
            "summary": self.summary(),
            "instances": [asdict(i) for i in self.instances],
            "reservations": [asdict(r) for r in self.reservations],
            "unknown_accelerated_types": self.unknown_accelerated_types,
            "errors": self.errors,
        }, indent=2, default=str)

    def summary_csv(self) -> str:
        buf = io.StringIO()
        cols = ["account", "region", "instance_type", "gpu_model", "capacity_type", "instances", "gpus"]
        w = csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        w.writerows(self.summary())
        return buf.getvalue()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _capacity_type(inst: dict[str, Any], reservations: dict[str, Reservation]) -> str:
    lifecycle = inst.get("InstanceLifecycle")
    if lifecycle == "capacity-block":
        return "capacity-block"
    if lifecycle == "spot":
        return "spot"
    res_id = inst.get("CapacityReservationId")
    if res_id:
        res = reservations.get(res_id)
        return res.kind if res else "odcr"
    return "on-demand"


def collect_region(account: str, region: str, ec2: Any, inv: Inventory) -> None:
    reservations: dict[str, Reservation] = {}
    for page in ec2.get_paginator("describe_capacity_reservations").paginate():
        for r in page.get("CapacityReservations", []):
            itype = r["InstanceType"]
            per = gpus.gpus_for(itype)
            if per is None:
                continue
            res = Reservation(
                account=account, region=region,
                reservation_id=r["CapacityReservationId"], instance_type=itype,
                az=r.get("AvailabilityZone", ""),
                kind="capacity-block" if r.get("ReservationType") == "capacity-block" else "odcr",
                state=r.get("State", "unknown"),
                total_instances=r.get("TotalInstanceCount", 0),
                available_instances=r.get("AvailableInstanceCount", 0),
                gpus_total=per * r.get("TotalInstanceCount", 0),
                start=_iso(r.get("StartDate")), end=_iso(r.get("EndDate")),
            )
            reservations[res.reservation_id] = res
            inv.reservations.append(res)

    paginator = ec2.get_paginator("describe_instances")
    filters = [{"Name": "instance-state-name", "Values": LIVE_STATES}]
    for page in paginator.paginate(Filters=filters):
        for resv in page.get("Reservations", []):
            for inst in resv.get("Instances", []):
                itype = inst["InstanceType"]
                per = gpus.gpus_for(itype)
                if per is None:
                    if gpus.looks_accelerated(itype):
                        inv.unknown_accelerated_types[itype] = inv.unknown_accelerated_types.get(itype, 0) + 1
                    continue
                inv.instances.append(Instance(
                    account=account, region=region,
                    instance_id=inst["InstanceId"], instance_type=itype,
                    az=inst.get("Placement", {}).get("AvailabilityZone", ""),
                    state=inst.get("State", {}).get("Name", "unknown"),
                    capacity_type=_capacity_type(inst, reservations),
                    reservation_id=inst.get("CapacityReservationId"),
                    gpus=per,
                ))


def collect(
    accounts: Iterable[dict[str, str]],
    regions: Iterable[str],
    client_factory: ClientFactory,
) -> Inventory:
    inv = Inventory(collected_at=datetime.now(timezone.utc).isoformat())
    regions = list(regions)
    for acct in accounts:
        for region in regions:
            try:
                ec2 = client_factory(acct["id"], region)
                collect_region(acct["name"], region, ec2, inv)
            except Exception as exc:  # keep going; report what failed
                inv.errors.append(f"{acct['name']}/{region}: {exc}")
    return inv


def assume_role_factory(role_name: str, session_name: str = "fleetops-inventory") -> ClientFactory:
    """Build EC2 clients by assuming a read-only role in each account."""
    import boto3

    sts = boto3.client("sts")
    cache: dict[str, Any] = {}

    def factory(account_id: str, region: str) -> Any:
        if account_id not in cache:
            creds = sts.assume_role(
                RoleArn=f"arn:aws:iam::{account_id}:role/{role_name}",
                RoleSessionName=session_name,
            )["Credentials"]
            cache[account_id] = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
            )
        return cache[account_id].client("ec2", region_name=region)

    return factory
