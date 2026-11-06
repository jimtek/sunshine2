import json

from conftest import FakeEC2
from fleetops import inventory

RESERVATIONS = [
    {"CapacityReservationId": "cr-block", "InstanceType": "p5.48xlarge", "AvailabilityZone": "us-east-1a",
     "ReservationType": "capacity-block", "State": "active", "TotalInstanceCount": 4, "AvailableInstanceCount": 1},
    {"CapacityReservationId": "cr-odcr", "InstanceType": "p5en.48xlarge", "AvailabilityZone": "us-east-1b",
     "ReservationType": "default", "State": "active", "TotalInstanceCount": 2, "AvailableInstanceCount": 0},
    {"CapacityReservationId": "cr-cpu", "InstanceType": "m7i.large", "State": "active",
     "TotalInstanceCount": 10, "AvailableInstanceCount": 10},
]


def inst(iid, itype, **extra):
    return {"InstanceId": iid, "InstanceType": itype, "State": {"Name": "running"},
            "Placement": {"AvailabilityZone": "us-east-1a"}, **extra}


INSTANCES = [
    inst("i-1", "p5.48xlarge", InstanceLifecycle="capacity-block", CapacityReservationId="cr-block"),
    inst("i-2", "p5.48xlarge", InstanceLifecycle="capacity-block", CapacityReservationId="cr-block"),
    inst("i-3", "p5.48xlarge", InstanceLifecycle="capacity-block", CapacityReservationId="cr-block"),
    inst("i-4", "p5en.48xlarge", CapacityReservationId="cr-odcr"),
    inst("i-5", "p5en.48xlarge", CapacityReservationId="cr-odcr"),
    inst("i-6", "p5.4xlarge"),
    inst("i-7", "g7.48xlarge"),      # unknown accelerated type
    inst("i-8", "m7i.large"),        # not a GPU
]


def make_inventory():
    fake = FakeEC2(INSTANCES, RESERVATIONS)
    accounts = [{"name": "research", "id": "111"}]
    return inventory.collect(accounts, ["us-east-1"], lambda a, r: fake)


def test_counts_gpus_and_capacity_types():
    inv = make_inventory()
    assert inv.total_gpus == 3 * 8 + 2 * 8 + 1
    by_type = {(r["instance_type"], r["capacity_type"]): r["gpus"] for r in inv.summary()}
    assert by_type[("p5.48xlarge", "capacity-block")] == 24
    assert by_type[("p5en.48xlarge", "odcr")] == 16
    assert by_type[("p5.4xlarge", "on-demand")] == 1


def test_reservations_skip_non_gpu_and_report_idle():
    inv = make_inventory()
    assert {r.reservation_id for r in inv.reservations} == {"cr-block", "cr-odcr"}
    assert inv.active_capacity_blocks() == 4
    assert inv.idle_reserved_gpus() == 8


def test_unknown_accelerated_types_are_surfaced():
    inv = make_inventory()
    assert inv.unknown_accelerated_types == {"g7.48xlarge": 1}


def test_errors_are_collected_not_raised():
    def boom(account, region):
        raise RuntimeError("AccessDenied")
    inv = inventory.collect([{"name": "partner", "id": "222"}], ["us-east-1"], boom)
    assert inv.errors == ["partner/us-east-1: AccessDenied"]


def test_outputs_serialise():
    inv = make_inventory()
    data = json.loads(inv.to_json())
    assert data["total_gpus"] == 41
    assert inv.summary_csv().splitlines()[0].startswith("account,region,instance_type")
