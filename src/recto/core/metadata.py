"""Reading, editing and stripping document metadata.

Two metadata systems coexist in a PDF: the classic **document info
dictionary** (``/Title``, ``/Author``, ...) and **XMP**, an embedded RDF/XML
packet. Editors write to one, the other, or both, and they routinely disagree.
Recto reads both and, when stripping, clears both — otherwise an author's name
survives in the XMP packet after being "removed" from the info dictionary.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from pypdf import PdfWriter

from .document import human_size, load_pdf, prepare_output, write_pdf
from .result import OperationResult
from .security import inspect_security

__all__ = ["FIELDS", "describe", "read_metadata", "set_metadata", "strip_metadata"]

#: Friendly names mapped to their info-dictionary keys.
FIELDS: Mapping[str, str] = {
    "title": "/Title",
    "author": "/Author",
    "subject": "/Subject",
    "keywords": "/Keywords",
    "creator": "/Creator",
    "producer": "/Producer",
}


def read_metadata(
    input_path: str | os.PathLike[str], *, password: str | None = None
) -> dict[str, Any]:
    """Return the info dictionary as a plain ``{friendly_name: value}`` dict."""
    loaded = load_pdf(input_path, password)
    info: Any = loaded.reader.metadata or {}
    result: dict[str, Any] = {}
    for name, key in FIELDS.items():
        value = info.get(key)
        result[name] = str(value) if value is not None else None
    result["created"] = _safe_date(info, "creation_date")
    result["modified"] = _safe_date(info, "modification_date")
    return result


def _safe_date(info: Any, attribute: str) -> str | None:
    """PDF dates are frequently malformed; never let that abort a read."""
    try:
        value = getattr(info, attribute, None)
    except Exception:
        return None
    return value.isoformat() if isinstance(value, datetime) else None


def describe(
    input_path: str | os.PathLike[str], *, password: str | None = None
) -> dict[str, Any]:
    """Full report on a document: structure, geometry, metadata and security.

    This is what ``recto info`` prints and what the web UI shows when a file is
    dropped in.
    """
    loaded = load_pdf(input_path, password)
    reader = loaded.reader

    sizes: dict[str, int] = {}
    rotations: dict[int, int] = {}
    for index, page in enumerate(reader.pages):
        box = page.mediabox
        label = f"{float(box.width) / 72:.2f} x {float(box.height) / 72:.2f} in"
        sizes[label] = sizes.get(label, 0) + 1
        rotation = int(page.rotation or 0)
        if rotation:
            rotations[index + 1] = rotation

    return {
        "path": str(loaded.path),
        "filename": loaded.path.name,
        "bytes": loaded.size,
        "size_human": human_size(loaded.size),
        "pages": loaded.page_count,
        "pdf_version": _pdf_version(loaded.data),
        "page_sizes": sizes,
        "rotated_pages": rotations,
        "has_outline": bool(_outline_count(reader)),
        "outline_entries": _outline_count(reader),
        "has_forms": _has_forms(reader),
        "attachments": _attachment_count(reader),
        "metadata": read_metadata(input_path, password=password),
        "security": inspect_security(input_path, password=password),
    }


def _pdf_version(data: bytes) -> str:
    header = data[:32]
    marker = header.find(b"%PDF-")
    if marker == -1:
        return "unknown"
    return header[marker + 5 : marker + 8].decode("ascii", "replace")


def _outline_count(reader: Any) -> int:
    def count(items: Any) -> int:
        total = 0
        for item in items:
            total += count(item) if isinstance(item, list) else 1
        return total

    try:
        return count(reader.outline)
    except Exception:  # pragma: no cover - malformed outline
        return 0


def _has_forms(reader: Any) -> bool:
    try:
        return bool(reader.get_fields())
    except Exception:  # pragma: no cover - malformed AcroForm
        return False


def _attachment_count(reader: Any) -> int:
    try:
        return len(reader.attachments or {})
    except Exception:  # pragma: no cover - malformed name tree
        return 0


def set_metadata(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    updates: Mapping[str, str | None],
    *,
    password: str | None = None,
    overwrite: bool = False,
    touch_modified: bool = True,
) -> OperationResult:
    """Apply metadata changes, leaving unmentioned fields alone.

    Args:
        updates: ``{friendly_name: value}``. A value of ``None`` clears that
            field; unlisted fields are preserved.
        touch_modified: Also set the modification date to now.

    Raises:
        InvalidDocument: An unknown field name was supplied.
    """
    from ..errors import InvalidDocument  # local import: avoids a cycle

    unknown = set(updates) - set(FIELDS)
    if unknown:
        raise InvalidDocument(
            f"Unknown metadata field(s): {', '.join(sorted(unknown))}.\n"
            f"Known fields: {', '.join(FIELDS)}."
        )

    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)

    writer = PdfWriter(clone_from=loaded.reader)
    existing = {str(k): str(v) for k, v in (loaded.reader.metadata or {}).items()}

    for name, value in updates.items():
        key = FIELDS[name]
        if value is None:
            existing.pop(key, None)
        else:
            existing[key] = value

    if touch_modified:
        existing["/ModDate"] = _pdf_date(datetime.now(timezone.utc))

    writer.metadata = None  # drop the cloned dictionary before rewriting it
    writer.add_metadata(existing)
    written = write_pdf(writer, target, overwrite=True)

    changed = sorted(updates)
    return OperationResult(
        outputs=[written],
        pages=loaded.page_count,
        summary=f"Updated metadata ({', '.join(changed) or 'no fields'})",
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"updated": changed},
    )


def strip_metadata(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    password: str | None = None,
    overwrite: bool = False,
    keep_producer: bool = False,
) -> OperationResult:
    """Remove the info dictionary and the XMP packet.

    Useful before sharing a document: those fields routinely carry a real name,
    a local file path, and the software used to produce the file.

    Args:
        keep_producer: Leave a ``/Producer`` line identifying Recto, instead of
            an entirely bare document.
    """
    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)

    from .. import __version__

    writer = PdfWriter(clone_from=loaded.reader)
    writer.metadata = None
    if keep_producer:
        writer.add_metadata({"/Producer": f"Recto {__version__}"})

    removed = ["document info"]
    try:
        writer.xmp_metadata = None
        removed.append("XMP")
    except Exception:  # pragma: no cover - older pypdf without the setter
        pass

    written = write_pdf(writer, target, overwrite=True)

    return OperationResult(
        outputs=[written],
        pages=loaded.page_count,
        summary=f"Stripped metadata ({' and '.join(removed)})",
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"removed": removed},
    )


def _pdf_date(moment: datetime) -> str:
    """Format a datetime as a PDF date string, e.g. ``D:20260812T...``."""
    stamp = moment.strftime("D:%Y%m%d%H%M%S")
    offset = moment.strftime("%z") or "+0000"
    return f"{stamp}{offset[:3]}'{offset[3:]}'"
