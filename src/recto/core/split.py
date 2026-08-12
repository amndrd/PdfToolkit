"""Break one PDF into several.

Five ways to cut, all producing the same shape of result:

===============  ==========================================================
``every``        fixed-size chunks — ``every=5`` gives 1-5, 6-10, ...
``into``         a fixed number of roughly equal parts
``at``           cut *before* the named pages — ``at="4,9"`` gives 1-3, 4-8, 9-
``ranges``       one file per explicit range — full control, may overlap
``outline``      one file per bookmark at a chosen outline depth
===============  ==========================================================
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pypdf import PdfReader

from ..errors import InvalidDocument, InvalidPageRange, UnsupportedOperation
from ..ranges import format_pages, parse_pages
from ._subset import build_subset
from .document import load_pdf, write_pdf
from .result import OperationResult

__all__ = ["Part", "SplitMode", "plan_split", "split"]

SplitMode = Literal["every", "into", "at", "ranges", "outline"]

#: Characters that are unsafe or annoying in filenames on some platform.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

DEFAULT_TEMPLATE = "{stem}-{index:03d}.pdf"


@dataclass(slots=True)
class Part:
    """One output document: a label and the pages that go into it."""

    label: str
    indices: list[int]


# --------------------------------------------------------------------------- #
# Planning — decide the cuts without writing anything
# --------------------------------------------------------------------------- #


def plan_split(
    reader: PdfReader,
    *,
    mode: SplitMode,
    every: int | None = None,
    into: int | None = None,
    at: str | None = None,
    ranges: Sequence[str] | None = None,
    outline_depth: int = 1,
) -> list[Part]:
    """Work out the parts a split would produce, without touching the disk.

    Exposed separately so the CLI can offer ``--dry-run`` and the web UI can
    preview a split before committing to it.
    """
    total = len(reader.pages)

    if mode == "every":
        if not every or every < 1:
            raise InvalidPageRange("--every needs a positive number of pages.")
        return [
            _part(list(range(start, min(start + every, total))))
            for start in range(0, total, every)
        ]

    if mode == "into":
        if not into or into < 1:
            raise InvalidPageRange("--into needs a positive number of parts.")
        if into > total:
            raise InvalidPageRange(
                f"Cannot split {total} pages into {into} parts — "
                f"there would be empty files."
            )
        # Distribute the remainder across the leading parts, so a 10-page
        # document split into 3 gives 4 + 3 + 3 rather than 4 + 4 + 2.
        base, remainder = divmod(total, into)
        parts: list[Part] = []
        cursor = 0
        for position in range(into):
            size = base + (1 if position < remainder else 0)
            parts.append(_part(list(range(cursor, cursor + size))))
            cursor += size
        return parts

    if mode == "at":
        if not at:
            raise InvalidPageRange("--at needs at least one page number.")
        cuts = sorted({i for i in parse_pages(at, total, unique=True) if i > 0})
        if not cuts:
            raise InvalidPageRange(
                "--at cannot cut before page 1; that would produce an empty first file."
            )
        boundaries = [0, *cuts, total]
        return [
            _part(list(range(start, end)))
            for start, end in pairwise(boundaries)
            if end > start
        ]

    if mode == "ranges":
        if not ranges:
            raise InvalidPageRange("--range needs at least one page range.")
        return [_part(parse_pages(spec, total)) for spec in ranges]

    if mode == "outline":
        return _plan_from_outline(reader, total, outline_depth)

    raise UnsupportedOperation(f"Unknown split mode: {mode!r}")


def _part(indices: list[int]) -> Part:
    return Part(label=format_pages(indices), indices=indices)


def _plan_from_outline(reader: PdfReader, total: int, depth: int) -> list[Part]:
    """One part per bookmark at ``depth``, spanning until the next one."""
    if depth < 1:
        raise InvalidPageRange("--outline-depth starts at 1.")

    marks = _outline_marks(reader, depth)
    if not marks:
        raise UnsupportedOperation(
            "This document has no bookmarks at the requested depth, so there "
            "is nothing to split on. Try --every or --into instead."
        )

    # A leading section before the first bookmark still deserves a file.
    if marks[0][0] > 0:
        marks.insert(0, (0, "front-matter"))

    parts: list[Part] = []
    for position, (start, title) in enumerate(marks):
        end = marks[position + 1][0] if position + 1 < len(marks) else total
        if end > start:
            parts.append(Part(label=title, indices=list(range(start, end))))
    return parts


def _outline_marks(reader: PdfReader, depth: int) -> list[tuple[int, str]]:
    """Collect ``(page_index, title)`` for outline entries at ``depth``."""
    marks: list[tuple[int, str]] = []

    def walk(items: Sequence[object], level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            if level != depth:
                continue
            try:
                page = reader.get_destination_page_number(item)  # type: ignore[arg-type]
            except Exception:  # pragma: no cover - broken destination
                continue
            title = str(getattr(item, "title", "") or "section").strip()
            if page is not None and page >= 0:
                marks.append((page, title))

    try:
        walk(reader.outline, 1)
    except Exception as exc:  # pragma: no cover - malformed outline tree
        raise UnsupportedOperation(f"Could not read the outline: {exc}") from exc

    marks.sort(key=lambda mark: mark[0])
    return marks


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #


def split(
    input_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    mode: SplitMode = "every",
    every: int | None = None,
    into: int | None = None,
    at: str | None = None,
    ranges: Sequence[str] | None = None,
    outline_depth: int = 1,
    template: str = DEFAULT_TEMPLATE,
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Split ``input_path`` into ``output_dir`` and return what was written.

    Args:
        input_path: Source document.
        output_dir: Directory for the parts; created if missing.
        mode: Which strategy to use — see the module docstring.
        every: Pages per part, for ``mode="every"``.
        into: Number of parts, for ``mode="into"``.
        at: Page-range expression naming cut points, for ``mode="at"``.
        ranges: Explicit page ranges, one output each, for ``mode="ranges"``.
        outline_depth: Bookmark depth to cut on, for ``mode="outline"``.
        template: Output filename pattern. Available fields: ``{stem}``,
            ``{index}`` (1-based), ``{start}``, ``{end}``, ``{count}``,
            ``{label}``.
        password: Password for an encrypted source.
        overwrite: Allow replacing existing files in ``output_dir``.

    Returns:
        An :class:`OperationResult` listing every file written.
    """
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

    directory = Path(output_dir).expanduser()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InvalidDocument(f"Cannot create {directory}: {exc}") from exc

    stem = loaded.path.stem
    written: list[Path] = []
    breakdown: list[dict[str, object]] = []
    total_bytes = 0

    for position, part in enumerate(parts, start=1):
        name = _render_name(template, stem=stem, index=position, part=part)
        destination = directory / name

        writer = build_subset(loaded.reader, part.indices)
        path = write_pdf(writer, destination, overwrite=overwrite)

        size = path.stat().st_size
        total_bytes += size
        written.append(path)
        breakdown.append(
            {
                "path": str(path),
                "pages": len(part.indices),
                "range": format_pages(part.indices),
                "label": part.label,
                "bytes": size,
            }
        )

    return OperationResult(
        outputs=written,
        pages=sum(len(p.indices) for p in parts),
        # The destination is deliberately left out of the summary: the CLI
        # prints it on its own line, and in the web UI it is a temporary
        # directory the user has no use for.
        summary=(
            f"Split {loaded.path.name} ({loaded.page_count} pages) into "
            f"{len(written)} files"
        ),
        input_bytes=loaded.size,
        output_bytes=total_bytes,
        details={"parts": breakdown, "mode": mode, "directory": str(directory)},
    )


def _render_name(template: str, *, stem: str, index: int, part: Part) -> str:
    """Fill the filename template, keeping the result filesystem-safe."""
    fields = {
        "stem": stem,
        "index": index,
        "start": part.indices[0] + 1 if part.indices else 0,
        "end": part.indices[-1] + 1 if part.indices else 0,
        "count": len(part.indices),
        "label": _slugify(part.label),
    }
    try:
        name = template.format(**fields)
    except (KeyError, IndexError, ValueError) as exc:
        raise InvalidDocument(
            f"Invalid filename template {template!r}: {exc}\n"
            f"Available fields: {', '.join(sorted(fields))}"
        ) from exc

    name = _UNSAFE.sub("-", name).strip(". ")
    if not name:
        name = f"{stem}-{index:03d}.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:200]


def _slugify(text: str) -> str:
    slug = _UNSAFE.sub("-", text)
    slug = re.sub(r"\s+", "-", slug).strip("-").lower()
    return slug or "part"
