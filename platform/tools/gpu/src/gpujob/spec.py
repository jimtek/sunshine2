"""The job spec researchers write: a small YAML file, one job per file.

    name: llama-8b-sft
    team: team-alpha
    project: llm-sft
    experiment: exp-042
    image: nvcr.io/nvidia/pytorch:24.10-py3
    command: [python, train.py, --config, configs/8b.yaml]
    gpus: 16
    max_runtime: 12h
    checkpoint_dir: s3://my-bucket/checkpoints/exp-042
    data: [s3://my-bucket/datasets/sft-v3]
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

import yaml


@dataclass
class JobSpec:
    name: str
    team: str
    project: str
    experiment: str
    image: str
    command: list[str]
    gpus: int
    max_runtime: str = "4h"
    priority: str | None = None
    pool: str | None = None
    checkpoint_dir: str | None = None
    data: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    resume_tested: bool = False
    cuda: str | None = None       # override when the image tag doesn't show it
    # Simulation only: annotations to add to the pod template.
    pod_annotations: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobSpec":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown field(s) in job spec: {', '.join(sorted(unknown))}")
        required = ["name", "team", "project", "experiment", "image", "command", "gpus"]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"job spec is missing: {', '.join(missing)}")
        d = dict(data)
        if isinstance(d["command"], str):
            d["command"] = ["/bin/sh", "-c", d["command"]]
        d["gpus"] = int(d["gpus"])
        return cls(**d)

    @classmethod
    def load(cls, path: str) -> "JobSpec":
        with open(path) as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})
