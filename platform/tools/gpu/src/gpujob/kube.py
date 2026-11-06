"""Thin kubectl wrapper. Uses the caller's kubeconfig and permissions."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import yaml


class KubeError(RuntimeError):
    pass


class Kubectl:
    def __init__(self, context: str | None = None, binary: str = "kubectl"):
        self.base = [binary] + (["--context", context] if context else [])

    def _run(self, args: list[str], stdin: str | None = None, capture: bool = True) -> str:
        proc = subprocess.run(self.base + args, input=stdin, text=True,
                              capture_output=capture, check=False)
        if proc.returncode != 0:
            raise KubeError((proc.stderr or "").strip() or f"kubectl {' '.join(args)} failed")
        return proc.stdout if capture else ""

    def apply(self, docs: list[dict[str, Any]]) -> str:
        return self._run(["apply", "-f", "-"], stdin=yaml.safe_dump_all(docs, sort_keys=False))

    def get_json(self, args: list[str]) -> dict[str, Any]:
        return json.loads(self._run(["get", *args, "-o", "json"]))

    def delete(self, kind: str, name: str, namespace: str) -> None:
        self._run(["delete", kind, name, "-n", namespace, "--ignore-not-found", "--wait=false"])

    def passthrough(self, args: list[str]) -> None:
        self._run(args, capture=False)
