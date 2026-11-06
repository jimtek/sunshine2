from pathlib import Path

import pytest

from fleetops import config

ROOT = Path(__file__).resolve().parents[3]


class FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **_):
        return iter(self._pages)


class FakeEC2:
    def __init__(self, instances=(), reservations=()):
        self._pages = {
            "describe_instances": [{"Reservations": [{"Instances": list(instances)}]}],
            "describe_capacity_reservations": [{"CapacityReservations": list(reservations)}],
        }

    def get_paginator(self, name):
        return FakePaginator(self._pages[name])


@pytest.fixture
def defaults():
    return config.load(ROOT / "config" / "fleet-defaults.yaml")
