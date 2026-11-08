"""Synthetic demo sample loading for the M5 UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def load_demo_cases() -> list[dict[str, Any]]:
    path = ROOT / "contracts" / "demo_cases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("demo_cases.json must contain a list")
    return data


def find_demo_case(sample_id: str) -> dict[str, Any]:
    for case in load_demo_cases():
        if case.get("sample_id") == sample_id:
            return case
    raise KeyError(f"unknown sample: {sample_id}")
