"""Page manipulation commands: delete, reorder, reverse, insert, duplicate."""

from pathlib import Path

import typer

from ...core import pages as core
from .. import options as opt
from ..render import render_result

app = typer.Typer()


@app.command()
def delete(
    input_path: Path = opt.InputFile,
    pages: str = opt.RequiredPages,
    output: Path | None = opt.OutputFile,
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Remove pages.

    recto delete report.pdf -p 2,5-7 -o trimmed.pdf
    recto delete report.pdf -p last --in-place
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core.delete(
        input_path, destination, pages, password=password, overwrite=overwrite
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def reorder(
    input_path: Path = opt.InputFile,
    order: str = typer.Option(
        ...,
        "--order",
        metavar="SEQUENCE",
        show_default=False,
        help="New page order, e.g. '3,1,2' or 'last,1-3'.",
    ),
    output: Path | None = opt.OutputFile,
    keep_unlisted: bool = typer.Option(
        False,
        "--keep-unlisted",
        help="Append pages the sequence did not mention instead of dropping them.",
    ),
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Rearrange pages into an explicit order.

    recto reorder deck.pdf --order 3,1,2 -o shuffled.pdf
    recto reorder deck.pdf --order last --keep-unlisted -o cover-last.pdf
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core.reorder(
        input_path,
        destination,
        order,
        password=password,
        overwrite=overwrite,
        keep_unlisted=keep_unlisted,
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def reverse(
    input_path: Path = opt.InputFile,
    output: Path | None = opt.OutputFile,
    pages: str | None = opt.Pages,
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Reverse page order, wholly or within a selection.

    recto reverse scanned.pdf -o corrected.pdf
    recto reverse scanned.pdf -p even -o backs-fixed.pdf
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core.reverse(
        input_path, destination, pages=pages, password=password, overwrite=overwrite
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def insert(
    base: Path = typer.Argument(
        ...,
        metavar="BASE",
        show_default=False,
        dir_okay=False,
        help="The document being inserted into.",
    ),
    source: Path = typer.Argument(
        ...,
        metavar="SOURCE",
        show_default=False,
        dir_okay=False,
        help="The document supplying the new pages.",
    ),
    output: Path | None = opt.OutputFile,
    at: int | None = typer.Option(
        None,
        "--at",
        metavar="N",
        show_default=False,
        help="Insert before page N. Omit to append at the end.",
    ),
    pages: str | None = typer.Option(
        None,
        "--pages",
        "-p",
        metavar="RANGE",
        show_default=False,
        help="Which pages of SOURCE to take. Defaults to all of them.",
    ),
    password: str | None = opt.Password,
    source_password: str | None = typer.Option(
        None,
        "--source-password",
        show_default=False,
        help="Password for SOURCE, if it differs from BASE's.",
    ),
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Splice one document into another.

    recto insert report.pdf cover.pdf --at 1 -o final.pdf
    recto insert report.pdf appendix.pdf -o final.pdf
    """
    destination, overwrite = opt.resolve_output(base, output, in_place, force)
    result = core.insert(
        base,
        source,
        destination,
        at=at,
        pages=pages,
        password=password,
        insert_password=source_password,
        overwrite=overwrite,
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def duplicate(
    input_path: Path = opt.InputFile,
    pages: str = opt.RequiredPages,
    output: Path | None = opt.OutputFile,
    times: int = typer.Option(
        1, "--times", "-n", metavar="N", help="Extra copies of each selected page."
    ),
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Repeat pages in place.

    recto duplicate form.pdf -p last -n 4 -o five-copies.pdf
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core.duplicate(
        input_path,
        destination,
        pages,
        times=times,
        password=password,
        overwrite=overwrite,
    )
    render_result(result, as_json=as_json, quiet=quiet)
