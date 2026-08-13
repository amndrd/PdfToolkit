"""Turning results and errors into terminal output.

One renderer for every command, so ``--json`` and ``--quiet`` work everywhere
without each command having to remember them.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.theme import Theme

from ..core.document import human_size
from ..core.result import OperationResult
from ..errors import RectoError

_THEME = Theme(
    {
        "ok": "bold green",
        "warn": "yellow",
        "err": "bold red",
        "dim": "dim",
        "key": "cyan",
    }
)

#: stdout — results. Errors go to stderr so `recto ... > file` stays clean.
console = Console(theme=_THEME)
error_console = Console(theme=_THEME, stderr=True)

__all__ = ["console", "error_console", "render_error", "render_mapping", "render_result"]


def render_result(
    result: OperationResult, *, as_json: bool = False, quiet: bool = False
) -> None:
    """Print what an operation produced."""
    if as_json:
        console.print_json(json.dumps(result.to_dict(), indent=2))
        return
    if quiet:
        return

    console.print(f"[ok]✓[/ok] {escape(result.summary)}")

    if len(result.outputs) == 1:
        console.print(f"  [key]output[/key] {escape(str(result.outputs[0]))}")
    elif result.outputs:
        for path in result.outputs[:10]:
            console.print(f"  [dim]•[/dim] {escape(path.name)}")
        if len(result.outputs) > 10:
            console.print(f"  [dim]… and {len(result.outputs) - 10} more[/dim]")
        console.print(f"  [key]directory[/key] {escape(str(result.outputs[0].parent))}")

    if result.input_bytes and result.output_bytes:
        console.print(f"  [key]size[/key]   {result.size_delta}")


def render_error(error: BaseException) -> int:
    """Print an error and return the exit code the process should use."""
    if isinstance(error, RectoError):
        error_console.print(f"[err]error:[/err] {escape(str(error))}")
        return error.exit_code

    error_console.print(f"[err]unexpected error:[/err] {escape(str(error))}")
    error_console.print(
        "[dim]This is a bug. Please report it with the command you ran:\n"
        "https://github.com/amndrd/PdfToolkit/issues[/dim]"
    )
    return 1


def render_mapping(title: str, data: Mapping[str, Any], *, as_json: bool = False) -> None:
    """Print a nested mapping as an indented table (used by ``info``)."""
    if as_json:
        console.print_json(json.dumps(data, indent=2, default=str))
        return

    table = Table(title=title, show_header=False, box=None, padding=(0, 2))
    table.add_column(style="key", justify="right", no_wrap=True)
    table.add_column(overflow="fold")

    _add_rows(table, data, depth=0)
    console.print(table)


def _add_rows(table: Table, data: Mapping[str, Any], *, depth: int) -> None:
    """Flatten a nested mapping into indented rows, at any depth."""
    indent = "  " * depth
    for key, value in data.items():
        if isinstance(value, Mapping):
            if not value:
                continue
            table.add_row(f"{indent}[bold]{_label(key)}[/bold]", "")
            _add_rows(table, value, depth=depth + 1)
        else:
            table.add_row(f"{indent}{_label(key)}", _format(value))


def _label(key: str) -> str:
    return escape(str(key).replace("_", " "))


def _format(value: Any) -> str:
    if value is None:
        return "[dim]—[/dim]"
    if isinstance(value, bool):
        return "[ok]yes[/ok]" if value else "[dim]no[/dim]"
    if isinstance(value, (list, tuple)):
        return escape(", ".join(str(item) for item in value)) or "[dim]—[/dim]"
    return escape(str(value))


def confirm_or_exit(message: str, *, assume_yes: bool) -> None:
    """Ask before doing something irreversible, unless told not to."""
    if assume_yes or not sys.stdin.isatty():
        return
    console.print(f"[warn]?[/warn] {message} [dim](y/N)[/dim] ", end="")
    if input().strip().lower() not in ("y", "yes"):
        console.print("[dim]Aborted.[/dim]")
        raise SystemExit(130)


def format_size(num_bytes: int) -> str:
    """Re-exported for command modules that report sizes directly."""
    return human_size(num_bytes)
