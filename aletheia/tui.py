"""Shared terminal UI helpers for the CLI."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


try:
    from rich import box
    from rich.columns import Columns
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.status import Status
    from rich.table import Table
    from rich.text import Text
except Exception:  # noqa: BLE001
    Columns = None
    Console = None
    Group = None
    Panel = None
    Status = None
    Table = None
    Text = None
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

    def panel(self, body: str, *, title: str = "", border: str = "cyan", dim: bool = False) -> None:
        """Render content inside a titled panel."""
        if self._enabled and self.console and Panel:
            style = "dim" if dim else border
            self.console.print(
                Panel(body, title=f"[bold]{title}[/bold]" if title else None,
                      border_style=style, padding=(1, 2)),
            )
            return
        if title:
            print(f"\n--- {title} ---")
        print(body)
        if title:
            print("---")

    def hint(self, message: str) -> None:
        """Render a dim guidance line."""
        if self._enabled and self.console:
            self.console.print(f"  [dim italic]{message}[/dim italic]")
            return
        print(f"  {message}")

    def status_dot(self, ok: bool, label: str, detail: str = "") -> str:
        """Return a styled status indicator line: ● Ready / ○ Not Ready."""
        if self._enabled:
            dot = "[green]●[/green]" if ok else "[red]○[/red]"
            state = "[green]Ready[/green]" if ok else "[red]Not ready[/red]"
            line = f"{dot} {label}  {state}"
            if detail:
                line += f"  [dim]{detail}[/dim]"
            return line
        dot = "●" if ok else "○"
        state = "Ready" if ok else "Not ready"
        line = f"{dot} {label}  {state}"
        if detail:
            line += f"  {detail}"
        return line

    @staticmethod
    def confidence_bar(value: float, *, width: int = 20) -> str:
        """Return a visual bar: ████████░░░░ 85%."""
        filled = int(value * width)
        empty = width - filled
        pct = f"{value:.0%}"
        bar = "█" * filled + "░" * empty
        if value >= 0.8:
            return f"[green]{bar}[/green] {pct}"
        if value >= 0.6:
            return f"[yellow]{bar}[/yellow] {pct}"
        return f"[red]{bar}[/red] {pct}"

    @staticmethod
    def confidence_bar_plain(value: float, *, width: int = 20) -> str:
        """Plain-text confidence bar."""
        filled = int(value * width)
        empty = width - filled
        return f"{'█' * filled}{'░' * empty} {value:.0%}"

    @staticmethod
    def decomposition_bar(method_share: float, *, width: int = 24) -> tuple[str, str]:
        """Return (methodology_line, real_line) for visual decomposition.

        Returns Rich-markup strings for methodology and real components.
        """
        real_share = 1.0 - method_share
        m_filled = max(1, int(method_share * width))
        r_filled = max(1, int(real_share * width))
        m_bar = "█" * m_filled + "░" * (width - m_filled)
        r_bar = "█" * r_filled + "░" * (width - r_filled)
        return (
            f"[yellow]{m_bar}[/yellow] {method_share:.0%} methodology",
            f"[cyan]{r_bar}[/cyan] {real_share:.0%} real change",
        )

    # -- Spinner support --------------------------------------------------

    def create_spinner(self) -> "PipelineSpinner":
        """Return a spinner that updates in-place during pipeline runs."""
        return PipelineSpinner(self)

    # -- Color-coded verdict helpers --------------------------------------

    @staticmethod
    def style_status(status: str) -> str:
        """Return Rich-markup string for a verdict status value."""
        _map = {
            "SUPPORTED": "[bold green]SUPPORTED[/bold green]",
            "PARTIALLY_SUPPORTED": "[bold yellow]PARTIALLY SUPPORTED[/bold yellow]",
            "MISLEADING": "[bold red]MISLEADING[/bold red]",
            "INSUFFICIENT_DATA": "[dim]INSUFFICIENT DATA[/dim]",
        }
        return _map.get(status.upper(), status)

    @staticmethod
    def style_confidence(value: float) -> str:
        """Return Rich-markup string for a confidence percentage."""
        pct = f"{value:.0%}"
        if value >= 0.8:
            return f"[green]{pct}[/green]"
        if value >= 0.6:
            return f"[yellow]{pct}[/yellow]"
        return f"[red]{pct}[/red]"

    @staticmethod
    def style_severity(severity: str) -> str:
        """Return Rich-markup string for a severity value."""
        _map = {
            "MAJOR": "[bold red]MAJOR[/bold red]",
            "MODERATE": "[yellow]MODERATE[/yellow]",
            "MINOR": "[dim]MINOR[/dim]",
        }
        return _map.get(severity.upper(), severity)

    @staticmethod
    def style_comparability(comp: str) -> str:
        """Return Rich-markup string for a comparability value."""
        _map = {
            "COMPARABLE": "[green]COMPARABLE[/green]",
            "UNCERTAIN": "[yellow]UNCERTAIN[/yellow]",
            "NOT_COMPARABLE": "[red]NOT COMPARABLE[/red]",
        }
        return _map.get(comp.upper(), comp)


class PipelineSpinner:
    """In-place spinner that tracks pipeline progress events.

    When Rich is available, uses ``rich.status.Status`` for animated updates.
    Falls back to plain ``print()`` lines otherwise.
    """

    def __init__(self, ui: TerminalUI):
        self._ui = ui
        self._status: Any | None = None  # rich.status.Status when active
        self._source_results: list[str] = []

    def start(self) -> None:
        if self._ui._enabled and self._ui.console and Status:
            self._status = self._ui.console.status(
                "[cyan]Starting pipeline...[/cyan]",
                spinner="dots",
            )
            self._status.start()
        else:
            print("Starting pipeline...")

    def stop(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    def update(self, event: dict[str, Any]) -> None:
        """Handle a progress_callback event from the orchestrator."""
        kind = event.get("event")
        msg = self._format_event(kind, event)
        if not msg:
            return

        if self._status is not None:
            # Build a multi-line status: current step + accumulated source results
            lines = list(self._source_results)
            lines.append(f"[cyan]{msg}[/cyan]")
            self._status.update("\n".join(lines))
        else:
            print(msg)

    def _format_event(self, kind: str | None, event: dict[str, Any]) -> str | None:
        if kind == "parser_started":
            return "Parsing claim..."
        if kind == "parser_completed":
            return "Claim parsed"
        if kind == "routing_selected":
            sources = event.get("source_ids") or []
            return f"Running {', '.join(sources)}..."
        if kind == "source_started":
            return f"Running {event.get('source_id')}..."
        if kind == "source_completed":
            sid = event.get("source_id")
            docs = event.get("doc_count", 0)
            breaks = event.get("break_count", 0)
            line = f"{sid} done ({breaks} breaks, {docs} docs)"
            self._source_results.append(f"[dim]  {line}[/dim]")
            return line
        if kind == "collection_completed":
            docs = event.get("evidence_count", 0)
            breaks = event.get("break_count", 0)
            conf = event.get("aggregate_confidence", 0.0)
            return f"Evidence collected ({docs} docs, {breaks} breaks, conf={conf:.2f})"
        if kind == "editor_started":
            return "Synthesizing verdict..."
        if kind == "editor_completed":
            return "Verdict ready"
        return None
