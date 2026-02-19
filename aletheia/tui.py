"""Shared terminal UI helpers for CLI and demo surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except Exception:  # noqa: BLE001
    Console = None
    Panel = None
    Table = None
    box = None


@dataclass(frozen=True)
class UIState:
    enabled: bool
    reason: str


class TerminalUI:
    """Thin wrapper over Rich with plain-text fallback."""

    def __init__(self, *, plain: bool = False):
        env_plain = os.environ.get("ALETHEIA_PLAIN_TUI", "0") == "1"
        no_color = "NO_COLOR" in os.environ
        rich_ready = Console is not None and Panel is not None and Table is not None

        self._enabled = rich_ready and not plain and not env_plain and not no_color
        self._reason = "rich" if self._enabled else "plain"
        self.console = Console() if self._enabled else None

    @property
    def state(self) -> UIState:
        return UIState(enabled=self._enabled, reason=self._reason)

    def banner(self, title: str, subtitle: str | None = None) -> None:
        if self._enabled and self.console and Panel:
            body = subtitle or ""
            self.console.print(
                Panel.fit(
                    body,
                    title=f"[bold]{title}[/bold]",
                    border_style="cyan",
                )
            )
            return
        print(f"\n{'=' * 78}")
        print(title)
        print("=" * 78)
        if subtitle:
            print(subtitle)

    def section(self, title: str) -> None:
        if self._enabled and self.console:
            self.console.rule(f"[bold]{title}[/bold]")
            return
        print(f"\n{title}")

    def info(self, message: str) -> None:
        if self._enabled and self.console:
            self.console.print(f"[cyan]{message}[/cyan]")
            return
        print(message)

    def success(self, message: str) -> None:
        if self._enabled and self.console:
            self.console.print(f"[green]{message}[/green]")
            return
        print(message)

    def warning(self, message: str) -> None:
        if self._enabled and self.console:
            self.console.print(f"[yellow]{message}[/yellow]")
            return
        print(message)

    def error(self, message: str) -> None:
        if self._enabled and self.console:
            self.console.print(f"[red]{message}[/red]")
            return
        print(message)

    def kv_table(self, title: str, rows: list[tuple[str, Any]]) -> None:
        if self._enabled and self.console and Table and box:
            table = Table(title=title, box=box.SIMPLE_HEAVY, show_header=False, pad_edge=False)
            table.add_column("key", style="bold cyan")
            table.add_column("value", style="white")
            for key, value in rows:
                table.add_row(str(key), str(value))
            self.console.print(table)
            return

        print(f"\n{title}")
        for key, value in rows:
            print(f"  {key}: {value}")

    def table(self, title: str, columns: list[str], rows: list[list[Any]]) -> None:
        if self._enabled and self.console and Table and box:
            table = Table(title=title, box=box.MINIMAL_DOUBLE_HEAD)
            for col in columns:
                table.add_column(str(col))
            for row in rows:
                table.add_row(*[str(cell) for cell in row])
            self.console.print(table)
            return

        print(f"\n{title}")
        print(" | ".join(columns))
        for row in rows:
            print(" | ".join(str(cell) for cell in row))

    def bullet_list(self, title: str, items: list[str]) -> None:
        if self._enabled and self.console:
            self.console.print(f"[bold]{title}[/bold]")
            for item in items:
                self.console.print(f" • {item}")
            return
        print(f"\n{title}")
        for item in items:
            print(f"- {item}")

    def thinking_block(self, reasoning: str, *, collapsed_label: str = "Thinking") -> None:
        """Display a reasoning/thinking block visually distinct from content."""
        if not reasoning or not reasoning.strip():
            return
        text = reasoning.strip()
        if self._enabled and self.console and Panel:
            self.console.print(
                Panel(
                    text,
                    title=f"[dim]{collapsed_label}[/dim]",
                    border_style="dim",
                    expand=False,
                )
            )
            return
        print(f"\n--- {collapsed_label} ---")
        for line in text.splitlines():
            print(f"  {line}")
        print(f"--- /{collapsed_label} ---")

    def status_badge(self, ok: bool) -> str:
        if self._enabled:
            return "[green]OK[/green]" if ok else "[red]MISSING[/red]"
        return "OK" if ok else "MISSING"
