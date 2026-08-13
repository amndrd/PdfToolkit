"""Shared fixtures.

Test documents are built with pypdf rather than checked in as binaries, so the
suite has no fixture files to keep in sync and every test can ask for exactly
the document it needs.

Pages are identified by giving each a unique width (200, 201, 202, ...). That
makes assertions about *order* trivial and exact — ``page_widths()`` returns a
fingerprint of the document that survives every operation Recto performs.
"""

from __future__ import annotations

import os

# Rich decides whether to emit ANSI escapes from the environment, and honours
# FORCE_COLOR even while pytest is capturing. Several tests assert on the exact
# text the CLI prints, so the environment is pinned here — before anything
# imports recto.cli, whose Console objects read it at construction time.
# Without this the suite passes locally and fails on any machine, or CI job,
# that happens to set FORCE_COLOR.
os.environ.pop("FORCE_COLOR", None)
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ["COLUMNS"] = "120"  # pin wrapping too, so line breaks stay stable

from collections.abc import Sequence
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

BASE_WIDTH = 200
PAGE_HEIGHT = 300


def make_pdf(
    path: str | Path,
    pages: int = 3,
    *,
    base_width: int = BASE_WIDTH,
    height: int = PAGE_HEIGHT,
    outline: Sequence[tuple[str, int]] | None = None,
    metadata: dict[str, str] | None = None,
    encrypt: str | None = None,
) -> Path:
    """Create a PDF whose pages are individually identifiable by width."""
    writer = PdfWriter()
    for offset in range(pages):
        writer.add_blank_page(width=base_width + offset, height=height)

    for title, index in outline or ():
        writer.add_outline_item(title, index)
    if metadata:
        writer.add_metadata(metadata)
    if encrypt is not None:
        writer.encrypt(encrypt, algorithm="AES-256")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def page_widths(path: str | Path, password: str | None = None) -> list[int]:
    """Fingerprint a document as the ordered list of its page widths."""
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        reader.decrypt(password or "")
    return [round(float(page.mediabox.width)) for page in reader.pages]


def page_count(path: str | Path, password: str | None = None) -> int:
    return len(page_widths(path, password))


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    """A 3-page document: widths 200, 201, 202."""
    return make_pdf(tmp_path / "sample.pdf", 3)


@pytest.fixture
def sample10(tmp_path: Path) -> Path:
    """A 10-page document: widths 200 through 209."""
    return make_pdf(tmp_path / "sample10.pdf", 10)


@pytest.fixture
def other(tmp_path: Path) -> Path:
    """A 2-page document whose widths (500, 501) cannot collide with `sample`."""
    return make_pdf(tmp_path / "other.pdf", 2, base_width=500)


@pytest.fixture
def outlined(tmp_path: Path) -> Path:
    """A 9-page document with three top-level bookmarks, at pages 1, 4 and 7."""
    return make_pdf(
        tmp_path / "outlined.pdf",
        9,
        outline=[("Chapter One", 0), ("Chapter Two", 3), ("Chapter Three", 6)],
    )


@pytest.fixture
def locked(tmp_path: Path) -> Path:
    """A 3-page AES-256 document whose password is ``s3cret``."""
    return make_pdf(tmp_path / "locked.pdf", 3, encrypt="s3cret")


@pytest.fixture
def out(tmp_path: Path) -> Path:
    """A destination path that does not exist yet."""
    return tmp_path / "out.pdf"
