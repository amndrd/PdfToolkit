"""The four headline commands: merge, split, rotate, extract."""

from pathlib import Path

import typer

from ...core import extract as core_extract
from ...core import merge as core_merge
from ...core import rotate as core_rotate
from ...core.document import collect_pdfs, load_pdf
from ...core.split import DEFAULT_TEMPLATE, SplitMode, plan_split
from ...core.split import split as core_split
from ...ranges import format_pages
from .. import options as opt
from ..render import console, render_result

app = typer.Typer()


@app.command()
def merge(
    inputs: list[str] = opt.InputFiles,
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        metavar="PATH",
        show_default=False,
        help="Where to write the merged PDF.",
    ),
    password: str | None = opt.Password,
    no_outline: bool = typer.Option(
        False,
        "--no-outline",
        help="Do not add a bookmark marking where each source file begins.",
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="Recurse into directory arguments."
    ),
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Combine several PDFs into one, in the order given.

    A trailing page range takes only part of a file:

        recto merge cover.pdf report.pdf:2-10 appendix.pdf -o final.pdf

    Directories contribute their PDFs, sorted naturally (page2 before page10):

        recto merge ./scans -o combined.pdf
    """
    expanded: list[str] = []
    for item in inputs:
        candidate = Path(item).expanduser()
        if candidate.is_dir():
            expanded.extend(
                str(p) for p in collect_pdfs([candidate], recursive=recursive)
            )
        else:
            expanded.append(item)

    result = core_merge(
        expanded,
        output,
        password=password,
        overwrite=force,
        outline=not no_outline,
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def split(
    input_path: Path = opt.InputFile,
    output: Path = opt.OutputDir,
    every: int | None = typer.Option(
        None,
        "--every",
        metavar="N",
        show_default=False,
        help="Fixed-size chunks of N pages each.",
    ),
    into: int | None = typer.Option(
        None,
        "--into",
        metavar="N",
        show_default=False,
        help="Split into N roughly equal parts.",
    ),
    at: str | None = typer.Option(
        None,
        "--at",
        metavar="PAGES",
        show_default=False,
        help="Cut before these pages, e.g. '4,9' gives 1-3, 4-8, 9-end.",
    ),
    ranges: list[str] | None = typer.Option(
        None,
        "--range",
        metavar="RANGE",
        show_default=False,
        help="One output per range. Repeatable: --range 1-3 --range 7-",
    ),
    outline: bool = typer.Option(False, "--outline", help="One output per bookmark."),
    outline_depth: int = typer.Option(
        1,
        "--outline-depth",
        metavar="N",
        help="Bookmark depth to cut on, when using --outline.",
    ),
    template: str = typer.Option(
        DEFAULT_TEMPLATE,
        "--template",
        metavar="PATTERN",
        help="Filename pattern. Fields: {stem} {index} {start} {end} {count} {label}",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show the planned parts without writing anything."
    ),
    password: str | None = opt.Password,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Break one PDF into several.

    Pick exactly one strategy:

        recto split book.pdf -o parts/ --every 10
        recto split book.pdf -o parts/ --into 3
        recto split book.pdf -o parts/ --at 5,20
        recto split book.pdf -o parts/ --range 1-3 --range 10-
        recto split book.pdf -o parts/ --outline
    """
    chosen = [
        name
        for name, value in (
            ("--every", every),
            ("--into", into),
            ("--at", at),
            ("--range", ranges),
            ("--outline", outline or None),
        )
        if value
    ]
    if len(chosen) != 1:
        raise typer.BadParameter(
            f"Pick exactly one split strategy, got {len(chosen)}"
            + (f" ({', '.join(chosen)})" if chosen else "")
            + ".\nChoose from: --every, --into, --at, --range, --outline."
        )

    # Keyed by the flag that was set, so the value is always a SplitMode.
    mode: SplitMode = {  # type: ignore[assignment]
        "--every": "every",
        "--into": "into",
        "--at": "at",
        "--range": "ranges",
        "--outline": "outline",
    }[chosen[0]]

    if dry_run:
        loaded = load_pdf(input_path, password)
        parts = plan_split(
            loaded.reader,
            mode=mode,
            every=every,
            into=into,
            at=at,
            ranges=ranges,
            outline_depth=outline_depth,
        )
        console.print(
            f"[ok]•[/ok] {loaded.path.name} ({loaded.page_count} pages) would "
            f"become {len(parts)} files:"
        )
        for index, part in enumerate(parts, start=1):
            console.print(
                f"  [dim]{index:>3}.[/dim] {format_pages(part.indices):<14} "
                f"[dim]{len(part.indices)} pages[/dim]  {part.label}"
            )
        return

    result = core_split(
        input_path,
        output,
        mode=mode,
        every=every,
        into=into,
        at=at,
        ranges=ranges,
        outline_depth=outline_depth,
        template=template,
        password=password,
        overwrite=force,
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def rotate(
    input_path: Path = opt.InputFile,
    degrees: int = typer.Option(
        ...,
        "--degrees",
        "-d",
        metavar="DEG",
        show_default=False,
        help="Any multiple of 90. Negative turns counter-clockwise.",
    ),
    output: Path | None = opt.OutputFile,
    pages: str | None = opt.Pages,
    absolute: bool = typer.Option(
        False,
        "--absolute",
        help="Set the rotation instead of adding to the current one.",
    ),
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Turn pages a quarter-turn at a time.

    recto rotate scan.pdf -d 90 -o fixed.pdf
    recto rotate scan.pdf -d -90 -p 2,4 --in-place
    recto rotate scan.pdf -d 0 --absolute -o straight.pdf
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core_rotate(
        input_path,
        destination,
        degrees,
        pages=pages,
        password=password,
        overwrite=overwrite,
        absolute=absolute,
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def extract(
    input_path: Path = opt.InputFile,
    pages: str = opt.RequiredPages,
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        metavar="PATH",
        show_default=False,
        help="Where to write the extracted pages.",
    ),
    sort: bool = typer.Option(
        False,
        "--sort",
        help="Force ascending page order, ignoring how --pages listed them.",
    ),
    unique: bool = typer.Option(
        False, "--unique", help="Drop repeated pages instead of duplicating them."
    ),
    password: str | None = opt.Password,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Pull selected pages into a new PDF.

    Page order is honoured, so this extracts and reorders in one step:

        recto extract report.pdf -p 1-3,10 -o excerpt.pdf
        recto extract report.pdf -p last,1 -o flipped.pdf
    """
    result = core_extract(
        input_path,
        output,
        pages,
        password=password,
        overwrite=force,
        sort=sort,
        unique=unique,
    )
    render_result(result, as_json=as_json, quiet=quiet)
