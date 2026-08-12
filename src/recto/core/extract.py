"""Pull a selection of pages out into a new document."""

from __future__ import annotations

import os

from ..ranges import describe_selection, parse_pages
from ._subset import build_subset
from .document import load_pdf, prepare_output, write_pdf
from .result import OperationResult

__all__ = ["extract"]


def extract(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    pages: str,
    *,
    password: str | None = None,
    overwrite: bool = False,
    unique: bool = False,
    sort: bool = False,
) -> OperationResult:
    """Write the pages named by ``pages`` into a new PDF.

    Args:
        input_path: Source document.
        output: Destination path.
        pages: Page-range expression — see :mod:`recto.ranges`. Order is
            honoured, so ``"3,1,2"`` extracts and reorders in one step.
        password: Password for an encrypted source.
        overwrite: Allow replacing an existing ``output``.
        unique: Drop repeated pages instead of duplicating them.
        sort: Force ascending document order regardless of how ``pages``
            listed them.

    Returns:
        An :class:`OperationResult` for the new file.
    """
    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)

    indices = parse_pages(pages, loaded.page_count, unique=unique, sort=sort)
    writer = build_subset(loaded.reader, indices)
    written = write_pdf(writer, target, overwrite=True)

    return OperationResult(
        outputs=[written],
        pages=len(indices),
        summary=(
            f"Extracted {describe_selection(indices, loaded.page_count)} "
            f"into {written.name}"
        ),
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"selection": pages, "source_pages": loaded.page_count},
    )
