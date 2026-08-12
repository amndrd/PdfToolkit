"""Compression and repair commands."""

from pathlib import Path

import typer

from ...core.optimize import optimize as core_optimize
from ...core.optimize import repair as core_repair
from .. import options as opt
from ..render import render_result

app = typer.Typer()

#: Presets, so the common cases do not require knowing what DPI to pick.
PRESETS = {
    "lossless": (None, None),
    "screen": (60, 100),
    "ebook": (75, 150),
    "print": (85, 300),
}


@app.command()
def compress(
    input_path: Path = opt.InputFile,
    output: Path | None = opt.OutputFile,
    preset: str | None = typer.Option(
        None,
        "--preset",
        metavar="NAME",
        show_default=False,
        help=(
            "lossless (structure only), screen (60q/100dpi), "
            "ebook (75q/150dpi), print (85q/300dpi)."
        ),
    ),
    image_quality: int | None = typer.Option(
        None,
        "--image-quality",
        "-q",
        metavar="1-100",
        show_default=False,
        help="Re-encode images as JPEG at this quality. Omit to stay lossless.",
    ),
    max_dpi: int | None = typer.Option(
        None,
        "--max-dpi",
        metavar="DPI",
        show_default=False,
        help="Downsample images above this resolution. Needs --image-quality.",
    ),
    linearize: bool = typer.Option(
        False, "--linearize", help="Optimise for fast web viewing."
    ),
    strip_metadata: bool = typer.Option(
        False, "--strip-metadata", help="Drop metadata while compressing."
    ),
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Make a PDF smaller.

    Without --image-quality the operation is lossless: streams are recompressed
    and duplicate objects removed, typically saving 5-20% on a text document.
    Scans need the image lever:

        recto compress scan.pdf --preset ebook -o small.pdf
        recto compress scan.pdf -q 75 --max-dpi 150 -o small.pdf
        recto compress report.pdf -o smaller.pdf          # lossless
    """
    if preset:
        key = preset.lower()
        if key not in PRESETS:
            raise typer.BadParameter(
                f"Unknown preset {preset!r}. Choose from: {', '.join(PRESETS)}."
            )
        if image_quality is not None or max_dpi is not None:
            raise typer.BadParameter(
                "--preset already sets quality and DPI; drop --image-quality "
                "and --max-dpi, or drop --preset."
            )
        image_quality, max_dpi = PRESETS[key]

    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core_optimize(
        input_path,
        destination,
        image_quality=image_quality,
        max_dpi=max_dpi,
        linearize=linearize,
        strip_metadata=strip_metadata,
        password=password,
        overwrite=overwrite,
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def repair(
    input_path: Path = opt.InputFile,
    output: Path | None = opt.OutputFile,
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Rebuild a damaged PDF so other tools will open it again.

    Recovers truncated downloads, broken cross-reference tables and malformed
    object streams. Content genuinely lost stays lost.

        recto repair broken.pdf -o fixed.pdf
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core_repair(input_path, destination, password=password, overwrite=overwrite)
    render_result(result, as_json=as_json, quiet=quiet)
