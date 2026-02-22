"""Compose helpers for ALETHEIA local deployments (single-file + profiles)."""

from __future__ import annotations

from dataclasses import dataclass, field

COMPOSE_FILE = "docker-compose.yml"


@dataclass(frozen=True)
class ComposePlan:
    """Resolved compose command with optional profiles."""

    files: list[str]
    profiles: list[str]
    command: list[str]


def compose_plan(
    *,
    profiles: list[str] | None = None,
    action: str = "up",
    detach: bool = True,
) -> ComposePlan:
    """Build a docker compose command with optional profile flags."""
    files = [COMPOSE_FILE]
    active_profiles = profiles or []

    command = ["docker", "compose", "-f", COMPOSE_FILE]
    for profile in active_profiles:
        command.extend(["--profile", profile])
    command.append(action)
    if detach and action == "up":
        command.append("-d")

    return ComposePlan(files=files, profiles=active_profiles, command=command)
