"""Exception hierarchy shared by the core library, the CLI and the web UI.

Every exception carries an ``exit_code`` so the CLI can map failures to
distinct process exit statuses, which makes Recto usable in shell scripts.
"""

from __future__ import annotations

__all__ = [
    "InvalidDocument",
    "InvalidPageRange",
    "MissingDependency",
    "OutputExists",
    "PasswordRequired",
    "RectoError",
    "UnsupportedOperation",
    "WrongPassword",
]


class RectoError(Exception):
    """Base class for every error Recto raises deliberately.

    Anything else escaping the core library is a bug.
    """

    exit_code = 1


class InvalidPageRange(RectoError):
    """A page-range expression is malformed or falls outside the document."""

    exit_code = 2


class PasswordRequired(RectoError):
    """The document is encrypted and no password was supplied."""

    exit_code = 3


class WrongPassword(RectoError):
    """The supplied password did not open the document."""

    exit_code = 4


class OutputExists(RectoError):
    """The destination already exists and overwriting was not requested."""

    exit_code = 5


class InvalidDocument(RectoError):
    """The file is not a usable PDF, or is damaged beyond what we can read."""

    exit_code = 6


class UnsupportedOperation(RectoError):
    """The request is well-formed but cannot be satisfied for this document."""

    exit_code = 7


class MissingDependency(RectoError):
    """An optional extra is required for this feature but is not installed."""

    exit_code = 8

    def __init__(self, package: str, feature: str, extra: str) -> None:
        self.package = package
        self.feature = feature
        self.extra = extra
        super().__init__(
            f"{feature} requires the optional dependency {package!r}, which is "
            f"not installed.\n"
            f"Install it with:  pip install 'recto[{extra}]'"
        )
