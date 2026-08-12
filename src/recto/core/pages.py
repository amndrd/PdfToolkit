"""Rearranging the pages of a document: delete, reorder, reverse, insert, duplicate."""

from __future__ import annotations

import os

from ..errors import InvalidDocument, InvalidPageRange
from ..ranges import describe_selection, format_pages, parse_pages
from ._subset import build_subset
from .document import load_pdf, prepare_output, write_pdf
from .result import OperationResult

__all__ = ["delete", "duplicate", "insert", "reorder", "reverse"]


def delete(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    pages: str,
    *,
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Write a copy of the document with ``pages`` removed.

    Raises:
        InvalidPageRange: The selection would remove every page.
    """
    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)

    doomed = set(parse_pages(pages, loaded.page_count, unique=True, sort=True))
    survivors = [i for i in range(loaded.page_count) if i not in doomed]

    if not survivors:
        raise InvalidPageRange(
            f"Deleting {pages!r} would remove all {loaded.page_count} pages, "
            f"leaving an empty document."
        )

    writer = build_subset(loaded.reader, survivors)
    written = write_pdf(writer, target, overwrite=True)

    return OperationResult(
        outputs=[written],
        pages=len(survivors),
        summary=(
            f"Deleted {len(doomed)} page{'s' if len(doomed) != 1 else ''} "
            f"({format_pages(sorted(doomed))}); {len(survivors)} remain"
        ),
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"deleted": format_pages(sorted(doomed))},
    )


def reorder(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    order: str,
    *,
    password: str | None = None,
    overwrite: bool = False,
    keep_unlisted: bool = False,
) -> OperationResult:
    """Rewrite the document with pages in the order ``order`` names.

    Args:
        order: Page-range expression read as a sequence, e.g. ``"3,1,2"`` or
            ``"last,1-3"``.
        keep_unlisted: Append any page the expression did not mention, in its
            original relative order, instead of dropping it.

    Returns:
        An :class:`OperationResult` for the reordered document.
    """
    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)

    sequence = parse_pages(order, loaded.page_count)
    if keep_unlisted:
        listed = set(sequence)
        sequence = sequence + [i for i in range(loaded.page_count) if i not in listed]

    writer = build_subset(loaded.reader, sequence)
    written = write_pdf(writer, target, overwrite=True)

    dropped = loaded.page_count - len({*sequence})
    return OperationResult(
        outputs=[written],
        pages=len(sequence),
        summary=(
            f"Reordered into {len(sequence)} pages"
            + (f" ({dropped} dropped)" if dropped else "")
        ),
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"order": order, "dropped": dropped},
    )


def reverse(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    pages: str | None = None,
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Reverse page order.

    Args:
        pages: Restrict the reversal to a selection. The selected pages swap
            places with each other while every other page stays put — handy for
            fixing a stack of double-sided scans fed in backwards.
    """
    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)

    sequence = list(range(loaded.page_count))
    if pages is None:
        sequence.reverse()
        scope = "all pages"
    else:
        selected = parse_pages(pages, loaded.page_count, unique=True, sort=True)
        for slot, value in zip(selected, reversed(selected), strict=True):
            sequence[slot] = value
        scope = describe_selection(selected, loaded.page_count)

    writer = build_subset(loaded.reader, sequence)
    written = write_pdf(writer, target, overwrite=True)

    return OperationResult(
        outputs=[written],
        pages=loaded.page_count,
        summary=f"Reversed {scope}",
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"scope": scope},
    )


def insert(
    base_path: str | os.PathLike[str],
    insert_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    at: int | None = None,
    pages: str | None = None,
    password: str | None = None,
    insert_password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Splice one document into another.

    Args:
        base_path: The document being inserted *into*.
        insert_path: The document supplying the new pages.
        at: 1-based page number to insert *before*. ``None`` appends at the
            end. ``at=1`` puts the new pages in front.
        pages: Restrict which pages of ``insert_path`` are taken.
        password: Password for ``base_path``.
        insert_password: Password for ``insert_path``.

    Raises:
        InvalidPageRange: ``at`` is outside ``1``..``page_count + 1``.
    """
    base = load_pdf(base_path, password)
    donor = load_pdf(insert_path, insert_password)
    target = prepare_output(output, overwrite=overwrite)

    position = base.page_count if at is None else at - 1
    if not 0 <= position <= base.page_count:
        raise InvalidPageRange(
            f"Cannot insert at page {at}: {base.path.name} has "
            f"{base.page_count} pages, so valid positions are 1 to "
            f"{base.page_count + 1}."
        )

    donor_indices = parse_pages(pages, donor.page_count, unique=True, sort=True)

    writer = build_subset(base.reader, list(range(position)))
    for index in donor_indices:
        writer.add_page(donor.reader.pages[index])
    for index in range(position, base.page_count):
        writer.add_page(base.reader.pages[index])

    written = write_pdf(writer, target, overwrite=True)
    total = base.page_count + len(donor_indices)

    return OperationResult(
        outputs=[written],
        pages=total,
        summary=(
            f"Inserted {len(donor_indices)} page"
            f"{'s' if len(donor_indices) != 1 else ''} from {donor.path.name} "
            f"at position {position + 1}; {total} pages total"
        ),
        input_bytes=base.size + donor.size,
        output_bytes=written.stat().st_size,
        details={"inserted_at": position + 1, "inserted_pages": len(donor_indices)},
    )


def duplicate(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    pages: str,
    *,
    times: int = 1,
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Repeat selected pages in place.

    Args:
        pages: Which pages to duplicate.
        times: How many extra copies of each. ``times=1`` doubles them.

    Raises:
        InvalidDocument: ``times`` is below 1.
    """
    if times < 1:
        raise InvalidDocument(f"--times must be at least 1, got {times}.")

    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)

    selected = set(parse_pages(pages, loaded.page_count, unique=True, sort=True))
    sequence: list[int] = []
    for index in range(loaded.page_count):
        sequence.append(index)
        if index in selected:
            sequence.extend([index] * times)

    writer = build_subset(loaded.reader, sequence)
    written = write_pdf(writer, target, overwrite=True)

    return OperationResult(
        outputs=[written],
        pages=len(sequence),
        summary=(
            f"Duplicated {len(selected)} page{'s' if len(selected) != 1 else ''} "
            f"x{times}; {loaded.page_count} -> {len(sequence)} pages"
        ),
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"duplicated": format_pages(sorted(selected)), "times": times},
    )
