"""The value every core operation returns.

One shape for every operation means the CLI renders results with one function
and the web API serialises them with one function. Adding an operation does not
mean touching either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .document import human_size

__all__ = ["OperationResult"]


@dataclass(slots=True)
class OperationResult:
    """What an operation produced, in a form both front-ends can render."""

    #: Files written, in the order they were created.
    outputs: list[Path] = field(default_factory=list)
    #: Pages in the result (summed, when several files were produced).
    pages: int = 0
    #: One-line human summary, e.g. ``"Merged 3 files into 24 pages"``.
    summary: str = ""
    #: Total bytes read.
    input_bytes: int = 0
    #: Total bytes written.
    output_bytes: int = 0
    #: Operation-specific extras (per-file breakdowns, warnings, ...).
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def output(self) -> Path:
        """The single output path, for operations that produce exactly one."""
        if len(self.outputs) != 1:
            raise ValueError(
                f"Expected exactly one output, got {len(self.outputs)}. "
                f"Use .outputs instead."
            )
        return self.outputs[0]

    @property
    def size_delta(self) -> str:
        """Readable before/after size line, e.g. ``'1.2 MB -> 480.0 KB (-61%)'``."""
        if not self.input_bytes or not self.output_bytes:
            return human_size(self.output_bytes)
        percent = (self.output_bytes - self.input_bytes) / self.input_bytes * 100
        return (
            f"{human_size(self.input_bytes)} -> {human_size(self.output_bytes)} "
            f"({percent:+.0f}%)"
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation, used by the web API and ``--json``."""
        return {
            "outputs": [str(p) for p in self.outputs],
            "pages": self.pages,
            "summary": self.summary,
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "details": self.details,
        }
