"""Password protection and permission flags.

A note on what PDF encryption actually buys you
-----------------------------------------------
PDF has two passwords. The **user password** is required to open the document
at all — that one is real encryption, and AES-256 is genuinely strong. The
**owner password** only guards the permission flags (may print, may copy
text, ...), and those flags are advisory: the content is decrypted either way,
and any compliant reader can ignore them. Recto exposes both, but does not
pretend the second is a security boundary.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from contextlib import suppress
from typing import Any

from pypdf import PdfWriter
from pypdf.constants import UserAccessPermissions as _Flags
from pypdf.errors import DependencyError as _DependencyError

from ..errors import InvalidDocument, MissingDependency, UnsupportedOperation
from .document import load_pdf, prepare_output, write_pdf
from .result import OperationResult

__all__ = [
    "ALGORITHMS",
    "PERMISSIONS",
    "decrypt",
    "encrypt",
    "inspect_security",
    "permissions_from_names",
]

#: Friendly names for the permission bits worth exposing.
PERMISSIONS: Mapping[str, _Flags] = {
    "print": _Flags.PRINT,
    "modify": _Flags.MODIFY,
    "copy": _Flags.EXTRACT,
    "annotate": _Flags.ADD_OR_MODIFY,
    "forms": _Flags.FILL_FORM_FIELDS,
    "accessibility": _Flags.EXTRACT_TEXT_AND_GRAPHICS,
    "assemble": _Flags.ASSEMBLE_DOC,
    "print-highres": _Flags.PRINT_TO_REPRESENTATION,
}

#: Encryption algorithms, weakest to strongest. Only the last is recommended.
ALGORITHMS: tuple[str, ...] = ("RC4-40", "RC4-128", "AES-128", "AES-256")

#: Bits 1 and 2 are reserved and must stay set in a well-formed /P value.
_RESERVED = 0b11111111111111111111111111111100 & ~sum(PERMISSIONS.values())


def permissions_from_names(names: Iterable[str]) -> _Flags:
    """Turn friendly permission names into a pypdf flag set.

    >>> int(permissions_from_names(["print"])) & int(PERMISSIONS["print"])
    4

    Raises:
        InvalidDocument: An unknown permission name was given.
    """
    flags = _Flags(_RESERVED)
    for raw in names:
        name = raw.strip().lower()
        if not name:
            continue
        if name == "all":
            return _Flags(_RESERVED | sum(PERMISSIONS.values()))
        if name == "none":
            continue
        if name not in PERMISSIONS:
            raise InvalidDocument(
                f"Unknown permission {raw!r}. Choose from: "
                f"{', '.join(sorted(PERMISSIONS))}, all, none."
            )
        flags |= PERMISSIONS[name]
    return flags


def encrypt(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    user_password: str,
    *,
    owner_password: str | None = None,
    allow: Iterable[str] = ("all",),
    algorithm: str = "AES-256",
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Encrypt a document with a password.

    Args:
        input_path: Source document.
        output: Destination path.
        user_password: Required to open the document. Pass ``""`` to leave the
            document openable by anyone while still setting permissions.
        owner_password: Grants full rights and lifts the permission flags.
            Defaults to ``user_password``.
        allow: Permission names to grant — see :data:`PERMISSIONS`, plus the
            shorthands ``"all"`` and ``"none"``.
        algorithm: One of :data:`ALGORITHMS`. Anything other than AES-256 is
            provided for compatibility with old readers, not for security.
        password: Password of the *source*, if it is already encrypted.
        overwrite: Allow replacing an existing ``output``.

    Raises:
        UnsupportedOperation: Unknown algorithm.
    """
    if algorithm not in ALGORITHMS:
        raise UnsupportedOperation(
            f"Unknown algorithm {algorithm!r}. Choose from: {', '.join(ALGORITHMS)}."
        )

    loaded = load_pdf(input_path, password)
    target = prepare_output(output, overwrite=overwrite)
    flags = permissions_from_names(allow)

    writer = PdfWriter(clone_from=loaded.reader)
    try:
        writer.encrypt(
            user_password=user_password,
            owner_password=owner_password or user_password,
            permissions_flag=flags,
            algorithm=algorithm,
        )
    except _DependencyError as exc:
        raise MissingDependency(
            "cryptography", f"{algorithm} encryption", "crypto"
        ) from exc
    written = write_pdf(writer, target, overwrite=True, compress=False)

    granted = sorted(n for n, bit in PERMISSIONS.items() if flags & bit)
    return OperationResult(
        outputs=[written],
        pages=loaded.page_count,
        summary=(
            f"Encrypted {written.name} with {algorithm} "
            f"({len(granted)}/{len(PERMISSIONS)} permissions granted)"
        ),
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
        details={"algorithm": algorithm, "granted": granted},
    )


def decrypt(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Write an unencrypted copy, removing passwords and permission flags.

    You need the password to do this — Recto does not crack anything.

    Raises:
        UnsupportedOperation: The document was not encrypted to begin with.
    """
    loaded = load_pdf(input_path, password)
    if not loaded.reader.is_encrypted:
        raise UnsupportedOperation(
            f"{loaded.path.name} is not encrypted; there is nothing to remove."
        )

    target = prepare_output(output, overwrite=overwrite)
    writer = PdfWriter(clone_from=loaded.reader)
    written = write_pdf(writer, target, overwrite=True)

    return OperationResult(
        outputs=[written],
        pages=loaded.page_count,
        summary=f"Removed encryption from {loaded.path.name}",
        input_bytes=loaded.size,
        output_bytes=written.stat().st_size,
    )


def inspect_security(
    input_path: str | os.PathLike[str], *, password: str | None = None
) -> dict[str, object]:
    """Report how a document is protected and what it permits."""
    loaded = load_pdf(input_path, password)
    reader = loaded.reader

    if not reader.is_encrypted:
        return {
            "encrypted": False,
            "algorithm": None,
            "permissions": dict.fromkeys(PERMISSIONS, True),
        }

    # A raw PDF dictionary rather than a typed object; read it defensively.
    encryption: Any = {}
    with suppress(Exception):  # pragma: no cover - unusual trailer layout
        encryption = reader.trailer["/Encrypt"].get_object()

    version = int(encryption.get("/V", 0) or 0)
    revision = int(encryption.get("/R", 0) or 0)
    raw_flags = int(encryption.get("/P", 0) or 0)
    flags = _Flags(raw_flags & 0xFFFFFFFF)

    return {
        "encrypted": True,
        "algorithm": _algorithm_name(version, revision, encryption),
        "key_bits": int(encryption.get("/Length", 40) or 40),
        "permissions": {name: bool(flags & bit) for name, bit in PERMISSIONS.items()},
    }


def _algorithm_name(version: int, revision: int, encryption: object) -> str:
    """Derive a readable algorithm name from /V, /R and the crypt filter."""
    if version >= 5:
        return "AES-256"
    if version == 4:
        try:
            method = encryption["/CF"]["/StdCF"]["/CFM"]  # type: ignore[index]
        except Exception:
            method = ""
        if str(method) == "/AESV2":
            return "AES-128"
        return "RC4-128"
    if version == 2 or revision == 3:
        return "RC4-128"
    return "RC4-40"
