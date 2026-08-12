"""Shared helper for building a new document from a selection of pages.

Every page-level operation (extract, delete, reorder, reverse, duplicate,
split) ultimately says "make a PDF out of these page indices, in this order".
Doing that well is subtler than looping over ``add_page``, so it lives in one
place.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from pypdf import PdfReader, PdfWriter

__all__ = ["build_subset", "is_simple_selection"]


def is_simple_selection(indices: Sequence[int]) -> bool:
    """True when the selection is strictly ascending with no repeats.

    Such a selection can go through :meth:`PdfWriter.append`, which carries
    across outlines, named destinations and inter-page links. Anything else —
    a reordering, a duplication — has to be assembled page by page, because
    those structures have no meaning once page order stops being monotonic.
    """
    return all(later > earlier for earlier, later in pairwise(indices))


def build_subset(
    reader: PdfReader,
    indices: Sequence[int],
    *,
    preserve_structure: bool = True,
) -> PdfWriter:
    """Return a writer containing ``indices`` from ``reader``, in that order.

    Args:
        reader: Source document.
        indices: 0-based page indices; order and repeats are honoured.
        preserve_structure: Carry outlines and links across when the selection
            allows it. Turn off for the smallest possible output.
    """
    writer = PdfWriter()

    if preserve_structure and is_simple_selection(indices):
        # ``append`` rewrites the outline tree and destination names to match
        # the surviving pages, and drops entries pointing at dropped pages.
        writer.append(reader, pages=list(indices))
        return writer

    for index in indices:
        writer.add_page(reader.pages[index])
    return writer
