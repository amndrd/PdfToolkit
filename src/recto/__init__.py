"""Recto — a local-first PDF toolkit.

Everything happens on your machine: no uploads, no telemetry, no network calls.

The public surface is :mod:`recto.core`; the CLI (:mod:`recto.cli`) and the
offline web UI (:mod:`recto.web`) are thin shells around it.

Example
-------
>>> from recto.core import merge
>>> merge(["a.pdf", "b.pdf"], "out.pdf")  # doctest: +SKIP
"""

from __future__ import annotations

__all__ = ["__version__", "errors", "ranges"]

__version__ = "0.1.0"
