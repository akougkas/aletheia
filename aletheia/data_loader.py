"""Load research/seed data from YAML files under data/."""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str):
    with open(_DATA_DIR / name) as f:
        return yaml.safe_load(f)


@functools.cache
def load_agencies() -> list[dict]:
    return _load("agencies.yaml")


@functools.cache
def load_datasets() -> list[dict]:
    return _load("datasets.yaml")


@functools.cache
def load_indicators() -> list[dict]:
    return _load("indicators.yaml")


@functools.cache
def load_methodology_breaks() -> list[dict]:
    return _load("methodology_breaks.yaml")


@functools.cache
def load_reference_docs() -> dict:
    return _load("reference_docs.yaml")


@functools.cache
def domain_to_agency_code() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for agency in load_agencies():
        for domain in agency.get("domains", []):
            mapping[domain] = agency["code"]
    return mapping
