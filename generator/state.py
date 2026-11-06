"""Remembers which records were already created in each system.

Maps our external ids (CMP-0001, DEAL-00012...) to the remote ids that
HubSpot or Stripe assigned. Saved after every batch, so an interrupted
load resumes where it stopped instead of creating duplicates.
"""

from __future__ import annotations

import json
from pathlib import Path


class LoadState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, dict[str, str]] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, kind: str, external_id: str) -> str | None:
        return self.data.get(kind, {}).get(external_id)

    def has(self, kind: str, external_id: str) -> bool:
        return self.get(kind, external_id) is not None

    def set(self, kind: str, external_id: str, remote_id: str) -> None:
        self.data.setdefault(kind, {})[external_id] = remote_id

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)  # atomic: never leaves a half-written file
