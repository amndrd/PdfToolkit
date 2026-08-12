"""Parsing and formatting of page-range expressions.

Recto speaks one page-range dialect everywhere — CLI flags, web UI fields and
library calls all funnel through :func:`parse_pages`. Page numbers are 1-based
because that is what users see in a PDF viewer; the parser returns 0-based
indices because that is what :mod:`pypdf` wants.

Grammar
-------
A specification is a comma-separated list of parts::

    all | *        every page
    even           every even-numbered page (2, 4, 6, ...)
    odd            every odd-numbered page (1, 3, 5, ...)
    N              a single page
    N-M            pages N through M, inclusive
    M-N            descending, when M > N (useful for reversing a selection)
    N-             page N through the end
    -M             the first page through M
    first, last    aliases usable anywhere a number is

Examples
--------
>>> parse_pages("1-3,7", 10)
[0, 1, 2, 6]
>>> parse_pages("last", 10)
[9]
>>> parse_pages("3-1", 10)
[2, 1, 0]
>>> parse_pages("odd", 6)
[0, 2, 4]
>>> format_pages([0, 1, 2, 5])
'1-3,6'

Order and duplicates are preserved, which is what makes ``reorder`` and
``duplicate`` expressible with the same syntax as ``extract``. Pass
``unique=True`` when a set is what you mean.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from .errors import InvalidPageRange

__all__ = ["describe_selection", "format_pages", "parse_pages"]

_NUMBER = r"(?:\d+|first|last)"
_SINGLE_RE = re.compile(rf"^(?P<value>{_NUMBER})$")
_CLOSED_RE = re.compile(rf"^(?P<start>{_NUMBER})-(?P<end>{_NUMBER})$")
_OPEN_END_RE = re.compile(rf"^(?P<start>{_NUMBER})-$")
_OPEN_START_RE = re.compile(rf"^-(?P<end>{_NUMBER})$")


def _resolve(token: str, page_count: int, spec: str) -> int:
    """Turn a single 1-based token into a validated 1-based page number."""
    if token == "first":
        return 1
    if token == "last":
        return page_count
    value = int(token)
    if value == 0:
        raise InvalidPageRange(
            f"Invalid page range {spec!r}: pages are numbered from 1, "
            f"so page 0 does not exist."
        )
    if value > page_count:
        raise InvalidPageRange(
            f"Invalid page range {spec!r}: page {value} is out of bounds — "
            f"the document has {page_count} page{'s' if page_count != 1 else ''}."
        )
    return value


def _span(start: int, end: int) -> list[int]:
    """Inclusive 1-based span, ascending or descending."""
    step = 1 if end >= start else -1
    return list(range(start, end + step, step))


def parse_pages(
    spec: str | None,
    page_count: int,
    *,
    unique: bool = False,
    sort: bool = False,
    allow_empty: bool = False,
) -> list[int]:
    """Parse ``spec`` against a document of ``page_count`` pages.

    Args:
        spec: The expression. ``None`` or an empty string means every page.
        page_count: Total pages in the target document.
        unique: Drop repeated pages, keeping first occurrence.
        sort: Return indices in ascending document order.
        allow_empty: Permit a selection that resolves to no pages.

    Returns:
        0-based page indices, in the order the expression named them.

    Raises:
        InvalidPageRange: The expression is malformed, out of bounds, or
            (unless ``allow_empty``) selects nothing.
    """
    if page_count <= 0:
        raise InvalidPageRange("The document has no pages to select from.")

    if spec is None or not spec.strip():
        pages = list(range(1, page_count + 1))
    else:
        pages = _parse_parts(spec, page_count)

    if unique:
        seen: set[int] = set()
        deduplicated: list[int] = []
        for page in pages:
            if page not in seen:
                seen.add(page)
                deduplicated.append(page)
        pages = deduplicated
    if sort:
        pages = sorted(pages)

    if not pages and not allow_empty:
        raise InvalidPageRange(f"Page range {spec!r} selects no pages.")

    return [p - 1 for p in pages]


def _parse_parts(spec: str, page_count: int) -> list[int]:
    pages: list[int] = []
    for raw in spec.split(","):
        # Whitespace is dropped entirely, not just trimmed, so a range typed
        # with breathing room ("1 - 3") parses like the compact form.
        part = "".join(raw.split()).lower()
        if not part:
            continue

        if part in ("all", "*"):
            pages.extend(range(1, page_count + 1))
        elif part == "even":
            pages.extend(range(2, page_count + 1, 2))
        elif part == "odd":
            pages.extend(range(1, page_count + 1, 2))
        elif match := _CLOSED_RE.match(part):
            start = _resolve(match["start"], page_count, spec)
            end = _resolve(match["end"], page_count, spec)
            pages.extend(_span(start, end))
        elif match := _OPEN_END_RE.match(part):
            start = _resolve(match["start"], page_count, spec)
            pages.extend(_span(start, page_count))
        elif match := _OPEN_START_RE.match(part):
            end = _resolve(match["end"], page_count, spec)
            pages.extend(_span(1, end))
        elif match := _SINGLE_RE.match(part):
            pages.append(_resolve(match["value"], page_count, spec))
        else:
            raise InvalidPageRange(
                f"Invalid page range {spec!r}: could not understand {raw.strip()!r}.\n"
                f"Expected something like '1', '2-5', '7-', '-3', 'last', "
                f"'odd', 'even' or 'all'."
            )
    return pages


def format_pages(indices: Iterable[int]) -> str:
    """Render 0-based indices as a compact 1-based expression.

    The inverse of :func:`parse_pages` for sorted, duplicate-free input. Runs
    of two are written out in full, since ``8,9`` is no longer than ``8-9``
    and reads more plainly.

    >>> format_pages([0, 1, 2, 4, 7, 8])
    '1-3,5,8,9'
    >>> format_pages([0, 1, 2, 3])
    '1-4'
    >>> format_pages([])
    'none'
    """
    numbers = sorted({int(i) + 1 for i in indices})
    if not numbers:
        return "none"

    chunks: list[str] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        chunks.append(_chunk(start, previous))
        start = previous = number
    chunks.append(_chunk(start, previous))
    return ",".join(chunks)


def _chunk(start: int, end: int) -> str:
    if start == end:
        return str(start)
    if end == start + 1:
        return f"{start},{end}"
    return f"{start}-{end}"


def describe_selection(indices: Sequence[int], page_count: int) -> str:
    """Human-readable summary used in CLI and API messages.

    The noun agrees with the total, not the selection, so a single page out of
    several still reads correctly.

    >>> describe_selection([0, 1, 2], 10)
    '3 of 10 pages (1-3)'
    >>> describe_selection([0], 3)
    '1 of 3 pages (1)'
    >>> describe_selection([0], 1)
    '1 of 1 page (1)'
    """
    noun = "page" if page_count == 1 else "pages"
    return f"{len(indices)} of {page_count} {noun} ({format_pages(indices)})"
