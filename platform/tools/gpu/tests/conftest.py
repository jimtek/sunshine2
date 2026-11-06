from datetime import datetime, timezone
from pathlib import Path

import pytest

from gpujob import platform
from gpujob.spec import JobSpec

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    return platform.load(ROOT / "config" / "platform.yaml")


@pytest.fixture
def spec():
    def make(**kw):
        base = dict(name="train-a", team="team-alpha", project="llm", experiment="exp-1",
                    image="nvcr.io/nvidia/pytorch:24.10-py3", command=["python", "train.py"],
                    gpus=16, max_runtime="12h", checkpoint_dir="s3://b/ckpt/exp-1")
        base.update(kw)
        return JobSpec.from_dict(base)
    return make
