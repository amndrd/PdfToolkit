"""Inspection and metadata commands."""

from pathlib import Path

import typer

from ...core.metadata import FIELDS, read_metadata
from ...core.metadata import describe as core_describe
from ...core.metadata import set_metadata as core_set
from ...core.metadata import strip_metadata as core_strip
from .. import options as opt
from ..render import render_mapping, render_result

app = typer.Typer()
meta_app = typer.Typer(help="Read, edit and remove document metadata.")


@app.command()
def info(
    input_path: Path = opt.InputFile,
    password: str | None = opt.Password,
    as_json: bool = opt.AsJson,
) -> None:
    """Report everything Recto can tell about a document.

    Page count and geometry, PDF version, bookmarks, form fields, attachments,
    metadata and encryption state.

        recto info report.pdf
        recto info report.pdf --json | jq .pages
    """
    data = core_describe(input_path, password=password)
    render_mapping(data["filename"], data, as_json=as_json)


@meta_app.command("show")
def meta_show(
    input_path: Path = opt.InputFile,
    password: str | None = opt.Password,
    as_json: bool = opt.AsJson,
) -> None:
    """Print the document's metadata fields."""
    data = read_metadata(input_path, password=password)
    render_mapping(f"{Path(input_path).name} — metadata", data, as_json=as_json)


@meta_app.command("set")
def meta_set(
    input_path: Path = opt.InputFile,
    output: Path | None = opt.OutputFile,
    title: str | None = typer.Option(None, "--title", show_default=False),
    author: str | None = typer.Option(None, "--author", show_default=False),
    subject: str | None = typer.Option(None, "--subject", show_default=False),
    keywords: str | None = typer.Option(None, "--keywords", show_default=False),
    creator: str | None = typer.Option(None, "--creator", show_default=False),
    producer: str | None = typer.Option(None, "--producer", show_default=False),
    clear: str | None = typer.Option(
        None,
        "--clear",
        metavar="FIELDS",
        show_default=False,
        help="Comma-separated fields to blank out: " + ", ".join(FIELDS) + ".",
    ),
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Edit metadata fields, leaving the others alone.

    recto meta set report.pdf --title "Q3 Results" --author "Finance" -o out.pdf
    recto meta set report.pdf --clear author,creator --in-place
    """
    updates: dict[str, str | None] = {
        name: value
        for name, value in (
            ("title", title),
            ("author", author),
            ("subject", subject),
            ("keywords", keywords),
            ("creator", creator),
            ("producer", producer),
        )
        if value is not None
    }
    for name in opt.parse_csv(clear):
        updates[name] = None

    if not updates:
        raise typer.BadParameter(
            "Nothing to change. Pass at least one field, e.g. --title, or use "
            "--clear to blank fields out."
        )

    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core_set(
        input_path, destination, updates, password=password, overwrite=overwrite
    )
    render_result(result, as_json=as_json, quiet=quiet)


@meta_app.command("strip")
def meta_strip(
    input_path: Path = opt.InputFile,
    output: Path | None = opt.OutputFile,
    keep_producer: bool = typer.Option(
        False, "--keep-producer", help="Leave a /Producer line identifying Recto."
    ),
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Remove all metadata, both the info dictionary and the XMP packet.

    Worth doing before sharing a document — those fields routinely carry a
    real name, a local file path, and the software that produced the file.

        recto meta strip contract.pdf -o anonymous.pdf
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core_strip(
        input_path,
        destination,
        password=password,
        overwrite=overwrite,
        keep_producer=keep_producer,
    )
    render_result(result, as_json=as_json, quiet=quiet)
