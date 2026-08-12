"""Rotate pages.

PDF stores rotation as a ``/Rotate`` entry on each page — a multiple of 90
degrees applied when the page is displayed. Nothing is re-rasterised, so
rotation is lossless and instant regardless of page size.
"""

from __future__ import annotations

import os

from pypdf import PdfWriter

from ..errors import InvalidPageRange
from ..ranges import describe_selection, parse_pages
from .document import load_pdf, prepare_output, write_pdf
from .result import OperationResult

__all__ = ["rotate"]


def rotate(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    degrees: int,
    *,
    pages: str | None = None,
    password: str | None = None,
    overwrite: bool = False,
    absolute: bool = False,
) -> OperationResult:
    """Turn some or all pages of a document.

    Args:
        input_path: Source document.
        output: Destination path.
        degrees: Any multiple of 90, positive (clockwise) or negative
            (counter-clockwise). Normalised into ``0``-``270``.
        pages: Page-range expression; ``None`` rotates every page.
        password: Password for an encrypted source.
        overwrite: Allow replacing an existing ``output``.
        absolute: Set the rotation instead of adding to what is already there.
            Use this to straighten a document whose pages disagree.

    Returns:
        An :class:`OperationResult` whose ``details['rotations']`` maps 1-based
        page numbers to their new absolute rotation.

    Raises:
        InvalidPageRange: ``degrees`` is not a multiple of 90.
    """
    if degrees % 90 != 0:
        raise InvalidPageRange(
            f"Rotation must be a multiple of 90 degrees, got {degrees}. "
            f"PDF only stores quarter-turns."
        )

    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)

    indices = parse_pages(pages, loaded.page_count, unique=True, sort=True)
    selected = set(indices)
    normalised = degrees % 360

    writer = PdfWriter(clone_from=loaded.reader)
    rotations: dict[int, int] = {}

    for index, page in enumerate(writer.pages):
        if index not in selected:
            continue
        current = int(page.rotation or 0)
        page.rotation = normalised if absolute else (current + normalised) % 360
        rotations[index + 1] = int(page.rotation)

    written = write_pdf(writer, target, overwrite=True)

    verb = "Set rotation to" if absolute else "Rotated"
    return OperationResult(
        outputs=[written],
        pages=loaded.page_count,
        summary=(
            f"{verb} {normalised}° on {describe_selection(indices, loaded.page_count)}"
        ),
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"rotations": rotations, "absolute": absolute},
    )
