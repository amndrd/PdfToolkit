"""The offline web interface.

Import :func:`recto.web.app.create_app` to mount Recto inside another ASGI
application, or run ``recto serve`` to start it standalone.
"""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str) -> object:
    """Defer importing FastAPI until the web app is actually asked for."""
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
