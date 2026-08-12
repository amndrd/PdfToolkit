"""Image conversion commands."""

from pathlib import Path

import typer

from ...core.images import FORMATS, PAGE_SIZES
from ...core.images import images_to_pdf as core_from_images
from ...core.images import pdf_to_images as core_to_images
from .. import options as opt
from ..render import render_result

app = typer.Typer()


@app.command("to-images")
def to_images(
    input_path: Path = opt.InputFile,
    output: Path = opt.OutputDir,
    dpi: int = typer.Option(
        150,
        "--dpi",
        metavar="N",
        help="Render resolution. 72 screen-size, 150 readable, 300 print.",
    ),
    fmt: str = typer.Option(
        "png",
        "--format",
        metavar="FMT",
        help="One of: " + ", ".join(sorted(FORMATS)) + ".",
    ),
    pages: str | None = opt.Pages,
    quality: int = typer.Option(
        90, "--quality", metavar="1-100", help="Encoder quality for JPEG and WebP."
    ),
    grayscale: bool = typer.Option(
        False, "--grayscale", help="Render without colour; much smaller output."
    ),
    template: str = typer.Option(
        "{stem}-{page:03d}{ext}",
        "--template",
        metavar="PATTERN",
        help="Filename pattern. Fields: {stem} {page} {index} {ext}",
    ),
    password: str | None = opt.Password,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Render pages to image files.

    recto to-images slides.pdf -o thumbnails/ --dpi 72
    recto to-images scan.pdf -o pages/ --format jpeg --grayscale -p 1-5
    """
    result = core_to_images(
        input_path,
        output,
        dpi=dpi,
        fmt=fmt,
        pages=pages,
        quality=quality,
        grayscale=grayscale,
        template=template,
        password=password,
        overwrite=force,
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command("from-images")
def from_images(
    images: list[Path] = typer.Argument(
        ...,
        metavar="IMAGES...",
        show_default=False,
        help="Image files, or directories to take images from.",
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        metavar="PATH",
        show_default=False,
        help="Where to write the PDF.",
    ),
    page_size: str = typer.Option(
        "auto",
        "--page-size",
        metavar="SIZE",
        help="'auto' fits each page to its image, or one of: "
        + ", ".join(sorted(PAGE_SIZES))
        + ".",
    ),
    margin: float = typer.Option(
        0.0,
        "--margin",
        metavar="POINTS",
        help="Margin in points, for fixed page sizes. 72 points = 1 inch.",
    ),
    dpi: int = typer.Option(150, "--dpi", metavar="N", help="Assumed image resolution."),
    quality: int = typer.Option(
        90, "--quality", metavar="1-100", help="JPEG quality for embedded images."
    ),
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Assemble images into a PDF, one image per page.

    Directory contents are sorted naturally, so page2.jpg precedes page10.jpg.

        recto from-images ./photos -o album.pdf
        recto from-images a.png b.png -o doc.pdf --page-size a4 --margin 36
    """
    result = core_from_images(
        images,
        output,
        page_size=page_size,
        margin=margin,
        dpi=dpi,
        quality=quality,
        overwrite=force,
    )
    render_result(result, as_json=as_json, quiet=quiet)
