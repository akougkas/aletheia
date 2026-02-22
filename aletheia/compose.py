"""Compose layering helpers for ALETHEIA local deployments."""

from __future__ import annotations

from dataclasses import dataclass

CORE_COMPOSE_FILE = "docker-compose.yml"
CRAWLER_COMPOSE_FILE = "docker-compose.crawler.yml"
LOCAL_OLLAMA_COMPOSE_FILE = "docker-compose.local-ollama.yml"


@dataclass(frozen=True)
class ComposePlan:
    """Resolved compose file stack and command line."""

    files: list[str]
    command: list[str]


def compose_file_stack(
    *,
    include_crawler: bool = False,
    include_local_ollama: bool = False,
) -> list[str]:
    """Resolve compose files in deterministic layering order."""
    files = [CORE_COMPOSE_FILE]
    if include_crawler:
        files.append(CRAWLER_COMPOSE_FILE)
    if include_local_ollama:
        files.append(LOCAL_OLLAMA_COMPOSE_FILE)
    return files


def compose_plan(
    *,
    include_crawler: bool = False,
    include_local_ollama: bool = False,
    action: str = "up",
    detach: bool = True,
) -> ComposePlan:
    """Build a docker compose command from selected layers."""
    files = compose_file_stack(
        include_crawler=include_crawler,
        include_local_ollama=include_local_ollama,
    )
    command = ["docker", "compose"]
    for compose_file in files:
        command.extend(["-f", compose_file])
    command.append(action)
    if detach and action == "up":
        command.append("-d")
    return ComposePlan(files=files, command=command)

