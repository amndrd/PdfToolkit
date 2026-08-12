"""Reading, writing and guarding PDF files.

Two invariants hold across the whole toolkit, and they live here:

1. **Inputs are read into memory before anything is written.** PDF readers are
   lazy — they seek back into the file as pages are touched. Buffering up front
   is what makes in-place edits (``--in-place``) safe, and makes them behave
   identically on Windows, where you cannot replace a file another handle has
   open.

2. **Outputs are written atomically.** We write to a sibling temporary file and
   ``os.replace`` it into position, so an interrupted run can never leave a
   half-written PDF where a valid one used to be.
"""

from __future__ import annotations

import io
import os
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import IO

from pypdf import PdfReader, PdfWriter
from pypdf.errors import (
    DependencyError,
    EmptyFileError,
    FileNotDecryptedError,
    PdfReadError,
    PdfStreamError,
    WrongPasswordError,
)

from ..errors import (
    InvalidDocument,
    MissingDependency,
    OutputExists,
    PasswordRequired,
    WrongPassword,
)

__all__ = [
    "LoadedPdf",
    "atomic_output",
    "collect_pdfs",
    "human_size",
    "load_pdf",
    "open_pdf",
    "page_count",
    "prepare_output",
    "require_optional",
    "write_pdf",
]

#: Magic bytes every PDF must start with (possibly after some leading junk).
_PDF_MAGIC = b"%PDF-"


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class LoadedPdf:
    """A fully buffered PDF, its reader, and where it came from."""

    path: Path
    reader: PdfReader
    data: bytes

    @property
    def page_count(self) -> int:
        return len(self.reader.pages)

    @property
    def size(self) -> int:
        return len(self.data)


def load_pdf(path: str | os.PathLike[str], password: str | None = None) -> LoadedPdf:
    """Read ``path`` into memory and return a decrypted reader for it.

    Args:
        path: Path to a PDF file.
        password: User or owner password, if the document is encrypted.

    Returns:
        A :class:`LoadedPdf` holding the bytes, the reader and the source path.

    Raises:
        InvalidDocument: The file is missing, empty, or not a readable PDF.
        PasswordRequired: The file is encrypted and no password was given.
        WrongPassword: The password did not open the file.
    """
    source = Path(path).expanduser()

    if not source.exists():
        raise InvalidDocument(f"No such file: {source}")
    if source.is_dir():
        raise InvalidDocument(f"Expected a PDF file but {source} is a directory.")

    try:
        data = source.read_bytes()
    except OSError as exc:  # unreadable, permissions, device errors
        raise InvalidDocument(f"Could not read {source}: {exc}") from exc

    if not data:
        raise InvalidDocument(f"{source} is empty.")
    if _PDF_MAGIC not in data[:1024]:
        raise InvalidDocument(
            f"{source} does not look like a PDF (missing %PDF- header).\n"
            f"If the file is damaged, try:  recto repair '{source}' -o fixed.pdf"
        )

    reader = _reader_from_bytes(data, password=password, label=str(source))
    return LoadedPdf(path=source, reader=reader, data=data)


def _reader_from_bytes(data: bytes, *, password: str | None, label: str) -> PdfReader:
    """Build a decrypted :class:`PdfReader` from raw bytes."""
    try:
        reader = PdfReader(io.BytesIO(data))
    except (EmptyFileError, PdfStreamError) as exc:
        raise InvalidDocument(f"{label} is not a valid PDF: {exc}") from exc
    except PdfReadError as exc:
        raise InvalidDocument(
            f"{label} could not be parsed: {exc}\n"
            f"Try:  recto repair '{label}' -o fixed.pdf"
        ) from exc

    if reader.is_encrypted:
        _decrypt(reader, password=password, label=label)

    # Touch the page tree so structural damage surfaces here rather than
    # halfway through an operation, with a partially written output on disk.
    try:
        len(reader.pages)
    except (PdfReadError, PdfStreamError, ValueError) as exc:
        raise InvalidDocument(
            f"{label} has a damaged page tree: {exc}\n"
            f"Try:  recto repair '{label}' -o fixed.pdf"
        ) from exc

    return reader


def _decrypt(reader: PdfReader, *, password: str | None, label: str) -> None:
    try:
        result = reader.decrypt(password or "")
    except DependencyError as exc:  # AES without the crypto backend
        raise MissingDependency(
            "cryptography", "Opening AES-encrypted PDFs", "crypto"
        ) from exc
    except (FileNotDecryptedError, WrongPasswordError, PdfReadError) as exc:
        raise WrongPassword(f"Could not decrypt {label}: {exc}") from exc

    if not result:
        if password:
            raise WrongPassword(f"The password supplied for {label} was rejected.")
        raise PasswordRequired(
            f"{label} is password-protected. Supply one with --password."
        )


def open_pdf(path: str | os.PathLike[str], password: str | None = None) -> PdfReader:
    """Convenience wrapper returning just the reader. See :func:`load_pdf`."""
    return load_pdf(path, password).reader


def page_count(path: str | os.PathLike[str], password: str | None = None) -> int:
    """Number of pages in ``path``."""
    return load_pdf(path, password).page_count


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def prepare_output(
    path: str | os.PathLike[str],
    *,
    overwrite: bool = False,
    make_parents: bool = True,
) -> Path:
    """Validate a destination path before any work is done.

    Failing here — rather than after minutes of processing — is the point.

    Raises:
        OutputExists: ``path`` exists and ``overwrite`` is False.
        InvalidDocument: ``path`` is a directory, or its parent is unusable.
    """
    target = Path(path).expanduser()

    if target.is_dir():
        raise InvalidDocument(
            f"{target} is a directory; give a file path for the output."
        )
    if target.exists() and not overwrite:
        raise OutputExists(f"{target} already exists. Pass --force to overwrite it.")

    parent = target.parent if str(target.parent) else Path()
    if make_parents:
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InvalidDocument(f"Cannot create {parent}: {exc}") from exc
    elif not parent.is_dir():
        raise InvalidDocument(f"Destination directory does not exist: {parent}")

    return target


@contextmanager
def atomic_output(
    path: str | os.PathLike[str], *, overwrite: bool = False
) -> Iterator[IO[bytes]]:
    """Yield a binary handle whose contents land at ``path`` atomically.

    The temporary file is created in the destination directory so the final
    ``os.replace`` stays on one filesystem and is therefore atomic. If the body
    raises, the temporary file is removed and ``path`` is left untouched.
    """
    target = prepare_output(path, overwrite=overwrite)
    handle, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    else:
        temp_path.replace(target)


def write_pdf(
    writer: PdfWriter,
    output: str | os.PathLike[str],
    *,
    overwrite: bool = False,
    compress: bool = True,
) -> Path:
    """Serialise ``writer`` to ``output`` atomically and return the path."""
    if compress:
        # Best-effort size win; never worth failing a write over.
        with suppress(Exception):
            writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)

    with atomic_output(output, overwrite=overwrite) as stream:
        writer.write(stream)
    return Path(output).expanduser()


# --------------------------------------------------------------------------- #
# Input collection
# --------------------------------------------------------------------------- #


def collect_pdfs(
    paths: Iterable[str | os.PathLike[str]], *, recursive: bool = False
) -> list[Path]:
    """Expand a mix of files and directories into a sorted list of PDF paths.

    Directories contribute their ``*.pdf`` children, sorted naturally so that
    ``page2.pdf`` precedes ``page10.pdf``. Explicit file arguments are kept in
    the order given, because for ``merge`` that order *is* the instruction.
    """
    collected: list[Path] = []
    for raw in paths:
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            pattern = "**/*.pdf" if recursive else "*.pdf"
            found = sorted(
                (p for p in candidate.glob(pattern) if p.is_file()),
                key=_natural_key,
            )
            if not found:
                raise InvalidDocument(f"No PDF files found in {candidate}")
            collected.extend(found)
        else:
            collected.append(candidate)

    if not collected:
        raise InvalidDocument("No input files were given.")
    return collected


def _natural_key(path: Path) -> tuple[object, ...]:
    """Sort key that orders embedded digit runs numerically."""
    parts: list[object] = []
    digits = ""
    for char in path.name.lower():
        if char.isdigit():
            digits += char
        else:
            if digits:
                parts.append((0, int(digits)))
                digits = ""
            parts.append((1, char))
    if digits:
        parts.append((0, int(digits)))
    return tuple(parts)


# --------------------------------------------------------------------------- #
# Optional dependencies
# --------------------------------------------------------------------------- #


#: Import paths whose installable name differs from the module name. The error
#: message has to name what the user types into pip, not what Python imports.
_DISTRIBUTION_NAMES = {"PIL": "Pillow"}


def require_optional(module: str, feature: str, extra: str) -> ModuleType:
    """Import an optional dependency or raise an actionable error.

    Recto keeps its base install small; rendering, image handling and
    qpdf-backed optimisation each live behind an extra.
    """
    try:
        return import_module(module)
    except ImportError as exc:  # pragma: no cover - depends on install shape
        top_level = module.split(".")[0]
        package = _DISTRIBUTION_NAMES.get(top_level, top_level)
        raise MissingDependency(package, feature, extra) from exc


def human_size(num_bytes: float) -> str:
    """Format a byte count the way a file manager would.

    >>> human_size(0)
    '0 B'
    >>> human_size(1536)
    '1.5 KB'
    """
    if num_bytes < 1024:
        return f"{int(num_bytes)} B"
    for unit in ("KB", "MB", "GB"):
        num_bytes /= 1024
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
    return f"{num_bytes / 1024:.1f} TB"
