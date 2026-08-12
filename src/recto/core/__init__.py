"""The Recto core library — every operation, importable without the CLI.

Each function takes paths, does one thing, and returns an
:class:`~recto.core.result.OperationResult`. Nothing here prints, prompts, or
touches global state, so the same call works in a script, a notebook, or a
web handler.

>>> from recto.core import merge, split, rotate, extract   # doctest: +SKIP
>>> result = merge(["a.pdf", "b.pdf"], "combined.pdf")     # doctest: +SKIP
>>> result.pages                                            # doctest: +SKIP
24
"""

from __future__ import annotations

from .document import (
    LoadedPdf,
    collect_pdfs,
    human_size,
    load_pdf,
    open_pdf,
    page_count,
)
from .extract import extract
from .images import images_to_pdf, pdf_to_images
from .merge import MergeSource, merge, parse_source
from .metadata import describe, read_metadata, set_metadata, strip_metadata
from .optimize import optimize, repair
from .pages import delete, duplicate, insert, reorder, reverse
from .result import OperationResult
from .rotate import rotate
from .security import decrypt, encrypt, inspect_security
from .split import split

# Deliberately grouped by theme rather than sorted: this list doubles as the
# table of contents for the library.
__all__ = [  # noqa: RUF022
    # Result and I/O
    "OperationResult",
    "LoadedPdf",
    "load_pdf",
    "open_pdf",
    "page_count",
    "collect_pdfs",
    "human_size",
    # The four essentials
    "merge",
    "split",
    "rotate",
    "extract",
    # Page manipulation
    "delete",
    "reorder",
    "reverse",
    "insert",
    "duplicate",
    # Security
    "encrypt",
    "decrypt",
    "inspect_security",
    # Metadata
    "describe",
    "read_metadata",
    "set_metadata",
    "strip_metadata",
    # Optimisation
    "optimize",
    "repair",
    # Images
    "pdf_to_images",
    "images_to_pdf",
    # Helpers
    "MergeSource",
    "parse_source",
]
