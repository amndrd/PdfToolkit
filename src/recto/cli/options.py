"""Reusable option and argument types.

Every command needs some of ``--output``, ``--password``, ``--pages``,
``--force``. Declaring them once means the help text, the short flags and the
semantics cannot drift apart between commands.

Note the deliberate absence of ``from __future__ import annotations`` here and
in the command modules: Typer resolves annotations at import time to build the
parser, and postponed evaluation makes that fragile.
"""

from pathlib import Path

import typer

__all__ = [
    "AsJson",
    "Force",
    "InPlace",
    "InputFile",
    "InputFiles",
    "OutputDir",
    "OutputFile",
    "Pages",
    "Password",
    "Quiet",
    "RequiredPages",
    "resolve_output",
]

InputFile = typer.Argument(
    ...,
    metavar="FILE",
    show_default=False,
    exists=False,  # checked by the core, which gives a better message
    dir_okay=False,
    help="Path to the PDF to work on.",
)

InputFiles = typer.Argument(
    ...,
    metavar="FILES...",
    show_default=False,
    help="PDF files, or directories to take PDFs from.",
)

OutputFile = typer.Option(
    None,
    "--output",
    "-o",
    metavar="PATH",
    show_default=False,
    help="Where to write the result. Required unless --in-place is used.",
)

OutputDir = typer.Option(
    ...,
    "--output",
    "-o",
    metavar="DIR",
    show_default=False,
    help="Directory to write the results into. Created if missing.",
)

Pages = typer.Option(
    None,
    "--pages",
    "-p",
    metavar="RANGE",
    show_default=False,
    help=(
        "Pages to act on, e.g. '1-3,7', '2-', '-5', 'last', 'odd', 'even'. "
        "Defaults to every page."
    ),
)

RequiredPages = typer.Option(
    ...,
    "--pages",
    "-p",
    metavar="RANGE",
    show_default=False,
    help="Pages to act on, e.g. '1-3,7', '2-', '-5', 'last', 'odd', 'even'.",
)

Password = typer.Option(
    None,
    "--password",
    metavar="TEXT",
    show_default=False,
    help="Password for an encrypted input.",
)

Force = typer.Option(
    False,
    "--force",
    "-f",
    help="Overwrite the output if it already exists.",
)

InPlace = typer.Option(
    False,
    "--in-place",
    "-i",
    help="Write the result back over the input file.",
)

AsJson = typer.Option(
    False,
    "--json",
    help="Emit machine-readable JSON instead of formatted text.",
)

Quiet = typer.Option(
    False,
    "--quiet",
    "-q",
    help="Suppress output; rely on the exit code.",
)


def resolve_output(
    input_path: Path,
    output: Path | None,
    in_place: bool,
    force: bool,
) -> "tuple[Path, bool]":
    """Work out where a single-input command should write, and whether it may.

    ``--in-place`` implies overwriting, and is safe because inputs are fully
    buffered before any byte is written (see :mod:`recto.core.document`).

    Returns:
        The destination path and the effective overwrite flag.

    Raises:
        typer.BadParameter: Neither or both of ``--output`` and ``--in-place``.
    """
    if in_place and output is not None:
        raise typer.BadParameter(
            "--in-place and --output are mutually exclusive; pick one."
        )
    if in_place:
        return input_path, True
    if output is None:
        raise typer.BadParameter(
            "Give a destination with --output/-o, or pass --in-place to "
            "overwrite the input."
        )
    return output, force


def parse_csv(value: str | None) -> list[str]:
    """Split a comma-separated option value into a clean list."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]
