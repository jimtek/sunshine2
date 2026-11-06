"""NVIDIA GPU instance types relevant to the fleet, and how many GPUs each has.

Only types in this table count as fleet capacity. Add new types as AWS ships
them; the inventory reports unknown accelerated types separately so nothing is
silently dropped.
"""

from __future__ import annotations

# instance type -> (gpus per instance, gpu model)
GPU_INSTANCE_TYPES: dict[str, tuple[int, str]] = {
    "p4d.24xlarge": (8, "A100-40GB"),
    "p4de.24xlarge": (8, "A100-80GB"),
    "p5.4xlarge": (1, "H100"),
    "p5.48xlarge": (8, "H100"),
    "p5e.48xlarge": (8, "H200"),
    "p5en.48xlarge": (8, "H200"),
    "p6-b200.48xlarge": (8, "B200"),
    "p6e-gb200.36xlarge": (4, "GB200"),
    "g5.48xlarge": (8, "A10G"),
    "g6e.48xlarge": (8, "L40S"),
}

ACCELERATED_PREFIXES = ("p", "g")


def family(instance_type: str) -> str:
    return instance_type.split(".", 1)[0]


def gpus_for(instance_type: str) -> int | None:
    entry = GPU_INSTANCE_TYPES.get(instance_type)
    return entry[0] if entry else None


def gpu_model(instance_type: str) -> str | None:
    entry = GPU_INSTANCE_TYPES.get(instance_type)
    return entry[1] if entry else None


def looks_accelerated(instance_type: str) -> bool:
    fam = family(instance_type)
    return fam[:1] in ACCELERATED_PREFIXES and fam[1:2].isdigit()
