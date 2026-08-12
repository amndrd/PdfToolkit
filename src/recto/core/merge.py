"""Combine several PDFs into one."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfWriter

from ..errors import InvalidDocument
from ..ranges import parse_pages
from .document import load_pdf, prepare_output, write_pdf
from .result import OperationResult

__all__ = ["MergeSource", "merge", "parse_source"]

#: A trailing ``:1-3`` or ``#1-3`` fragment naming a page selection.
_FRAGMENT_RE = re.compile(
    r"^(?P<path>.+?)[#:](?P<pages>[0-9,\-]*(?:all|even|odd|first|last)?[0-9,\-]*)$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class MergeSource:
    """One input to a merge: a file, optionally a subset of it."""

    path: Path
    pages: str | None = None
    password: str | None = None
    title: str | None = None


def parse_source(spec: str | os.PathLike[str]) -> MergeSource:
    """Parse ``report.pdf:1-3`` into a :class:`MergeSource`.

    Both ``:`` and ``#`` introduce the page selection. A path that exists on
    disk as written always wins, so ``C:\\scans\\a.pdf`` and files whose names
    genuinely contain a colon are never mangled.

    >>> parse_source("report.pdf:1-3").pages
    '1-3'
    >>> parse_source("report.pdf").pages is None
    True
    """
    text = os.fspath(spec)

    if Path(text).expanduser().exists():
        return MergeSource(path=Path(text).expanduser())

    match = _FRAGMENT_RE.match(text)
    if match and match["pages"].strip():
        return MergeSource(
            path=Path(match["path"]).expanduser(),
            pages=match["pages"].strip(),
        )
    return MergeSource(path=Path(text).expanduser())


def merge(
    inputs: Iterable[str | os.PathLike[str] | MergeSource],
    output: str | os.PathLike[str],
    *,
    password: str | None = None,
    overwrite: bool = False,
    outline: bool = True,
) -> OperationResult:
    """Concatenate ``inputs`` into a single PDF at ``output``.

    Args:
        inputs: Paths, ``path:pages`` specs, or :class:`MergeSource` objects.
            Order is preserved — it is the instruction.
        output: Destination path.
        password: Password tried against every encrypted input. Per-file
            passwords can be set on a :class:`MergeSource`.
        overwrite: Allow replacing an existing ``output``.
        outline: Add a top-level bookmark per source file, so the reader can
            still tell where each document begins. Source outlines are nested
            underneath and preserved either way.

    Returns:
        An :class:`OperationResult` whose ``details['sources']`` lists each
        input with its contributed page count.

    Raises:
        InvalidDocument: Fewer than two inputs, or an input is unreadable.
        OutputExists: ``output`` exists and ``overwrite`` is False.
    """
    sources = [s if isinstance(s, MergeSource) else parse_source(s) for s in inputs]
    if len(sources) < 2:
        raise InvalidDocument(
            f"Merging needs at least two input files, got {len(sources)}."
        )

    # Catch "the output is also an input" before the exists check, so that
    # case reports what is actually wrong instead of suggesting --force, which
    # would not fix it.
    resolved_target = Path(output).expanduser().resolve()
    for source in sources:
        if source.path.expanduser().resolve() == resolved_target:
            raise InvalidDocument(
                f"{source.path} is both an input and the output. Write the "
                f"merged file somewhere else."
            )

    # Validate the destination before reading gigabytes we may not be able to
    # write, and before any source is opened.
    target = prepare_output(output, overwrite=overwrite)

    writer = PdfWriter()
    breakdown: list[dict[str, object]] = []
    total_pages = 0
    total_input_bytes = 0

    for source in sources:
        loaded = load_pdf(source.path, source.password or password)
        indices = parse_pages(source.pages, loaded.page_count, sort=True, unique=True)

        writer.append(
            loaded.reader,
            outline_item=(source.title or source.path.stem) if outline else None,
            pages=indices,
        )

        total_pages += len(indices)
        total_input_bytes += loaded.size
        breakdown.append(
            {
                "path": str(source.path),
                "pages_taken": len(indices),
                "pages_total": loaded.page_count,
                "selection": source.pages or "all",
            }
        )

    written = write_pdf(writer, target, overwrite=True)

    return OperationResult(
        outputs=[written],
        pages=total_pages,
        summary=(
            f"Merged {len(sources)} files into {written.name} ({total_pages} pages)"
        ),
        input_bytes=total_input_bytes,
        output_bytes=written.stat().st_size,
        details={"sources": breakdown},
    )
