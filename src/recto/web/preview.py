"""Page thumbnails for the web interface.

The UI shows the document rather than describing it, which means rendering
every page to a small image. Two things make that affordable:

* **Caching.** A thumbnail is rendered once per (file, page, width) and kept in
  the workspace, which is discarded on shutdown along with everything else.
* **Laziness.** The browser only asks for thumbnails as they scroll into view,
  so a 300-page document costs the same as a 3-page one until you look.

Rendering needs the ``images`` extra. Without it the endpoint reports that
cleanly and the UI falls back to numbered placeholders — every tool still
works, you just do not see the pages.
"""

from __future__ import annotations

from pathlib import Path

from ..core.document import require_optional
from ..errors import InvalidDocument

__all__ = ["IMAGE_SUFFIXES", "THUMBNAIL_WIDTHS", "available", "render_thumbnail"]

#: Widths the endpoint will render, in CSS pixels. Restricting the set keeps
#: the cache small and stops a caller from asking for a 10000px render.
THUMBNAIL_WIDTHS: tuple[int, ...] = (160, 240, 480, 960)

#: Uploads we can preview directly rather than through a PDF renderer.
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
)


def available() -> bool:
    """Whether thumbnails can be rendered in this installation."""
    try:
        require_optional("pypdfium2", "Page previews", "images")
        require_optional("PIL", "Page previews", "images")
    except Exception:
        return False
    return True


def nearest_width(requested: int) -> int:
    """Snap a requested width to the nearest supported one."""
    return min(THUMBNAIL_WIDTHS, key=lambda w: abs(w - requested))


def render_thumbnail(
    source: Path,
    page: int,
    *,
    width: int,
    cache_dir: Path,
    password: str | None = None,
) -> Path:
    """Return a PNG thumbnail of ``page`` (0-based), rendering it if needed.

    Args:
        source: The uploaded file.
        page: 0-based page index. Ignored for image uploads.
        width: Target width in pixels; snapped to :data:`THUMBNAIL_WIDTHS`.
        cache_dir: Directory to keep rendered thumbnails in.
        password: Password for an encrypted PDF.

    Returns:
        Path to a PNG file.

    Raises:
        MissingDependency: The ``images`` extra is not installed.
        InvalidDocument: The page does not exist, or the file cannot be read.
    """
    target_width = nearest_width(width)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{page:05d}-{target_width}.png"
    if cached.exists():
        return cached

    if source.suffix.lower() in IMAGE_SUFFIXES:
        _render_image(source, cached, target_width)
    else:
        _render_pdf_page(source, cached, page, target_width, password)
    return cached


def _render_pdf_page(
    source: Path, destination: Path, page: int, width: int, password: str | None
) -> None:
    pdfium = require_optional("pypdfium2", "Page previews", "images")

    try:
        document = pdfium.PdfDocument(str(source), password=password)
    except Exception as exc:
        raise InvalidDocument(f"Could not open {source.name} for preview: {exc}") from exc

    try:
        if not 0 <= page < len(document):
            raise InvalidDocument(
                f"{source.name} has {len(document)} pages; page {page + 1} does not exist."
            )
        target = document[page]
        # ``get_width`` is in points; scale so the render lands on `width` px.
        points = float(target.get_width()) or 612.0
        bitmap = target.render(scale=max(width / points, 0.05))
        image = bitmap.to_pil()
        image.save(destination, format="PNG", optimize=True)
    finally:
        document.close()


def _render_image(source: Path, destination: Path, width: int) -> None:
    Image = require_optional("PIL.Image", "Page previews", "images")

    try:
        with Image.open(source) as handle:
            frame = handle.convert("RGB")
            height = max(1, round(frame.height * width / frame.width))
            frame.resize((width, height), Image.LANCZOS).save(
                destination, format="PNG", optimize=True
            )
    except Exception as exc:
        raise InvalidDocument(f"Could not read {source.name}: {exc}") from exc
