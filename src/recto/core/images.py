"""Conversion between PDFs and raster images.

PDF -> images renders through PDFium (the engine in Chrome's PDF viewer), so
what you get matches what a browser would show. images -> PDF wraps each
picture on a page without re-encoding it more than necessary.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..errors import InvalidDocument, UnsupportedOperation
from ..ranges import parse_pages
from .document import human_size, prepare_output, require_optional
from .result import OperationResult

__all__ = ["FORMATS", "PAGE_SIZES", "images_to_pdf", "pdf_to_images"]

#: Output formats for rendering, with the PIL format name and file extension.
FORMATS: dict[str, tuple[str, str]] = {
    "png": ("PNG", ".png"),
    "jpeg": ("JPEG", ".jpg"),
    "jpg": ("JPEG", ".jpg"),
    "tiff": ("TIFF", ".tif"),
    "webp": ("WEBP", ".webp"),
}

#: Named page sizes in points (1/72 inch).
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a4": (595.28, 841.89),
    "a3": (841.89, 1190.55),
    "a5": (420.94, 595.28),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
}

#: Image file suffixes accepted by :func:`images_to_pdf`.
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
)

DEFAULT_TEMPLATE = "{stem}-{page:03d}{ext}"


# --------------------------------------------------------------------------- #
# PDF -> images
# --------------------------------------------------------------------------- #


def pdf_to_images(
    input_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    dpi: int = 150,
    fmt: str = "png",
    pages: str | None = None,
    quality: int = 90,
    grayscale: bool = False,
    template: str = DEFAULT_TEMPLATE,
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Render pages to image files.

    Args:
        input_path: Source document.
        output_dir: Directory for the images; created if missing.
        dpi: Render resolution. 72 is screen-size, 150 reads well, 300 prints.
        fmt: One of :data:`FORMATS`.
        pages: Page-range expression; ``None`` renders every page.
        quality: Encoder quality for JPEG and WebP; ignored for PNG and TIFF.
        grayscale: Render without colour, which shrinks output substantially.
        template: Filename pattern with ``{stem}``, ``{page}``, ``{index}``
            and ``{ext}``.
        password: Password for an encrypted source.
        overwrite: Allow replacing existing image files.

    Raises:
        UnsupportedOperation: Unknown format.
        InvalidDocument: ``dpi`` outside a sane 12-1200 range.
    """
    pdfium = require_optional("pypdfium2", "Rendering PDF pages to images", "images")

    key = fmt.lower().lstrip(".")
    if key not in FORMATS:
        raise UnsupportedOperation(
            f"Unknown image format {fmt!r}. Choose from: {', '.join(sorted(FORMATS))}."
        )
    if not 12 <= dpi <= 1200:
        raise InvalidDocument(f"--dpi must be between 12 and 1200, got {dpi}.")

    pil_format, extension = FORMATS[key]
    source = Path(input_path).expanduser()
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)

    document = pdfium.PdfDocument(str(source), password=password)
    try:
        total = len(document)
        indices = parse_pages(pages, total, unique=True, sort=True)
        scale = dpi / 72.0

        written: list[Path] = []
        total_bytes = 0

        for position, index in enumerate(indices, start=1):
            bitmap = document[index].render(scale=scale, grayscale=grayscale)
            image = bitmap.to_pil()

            name = _render_name(
                template,
                stem=source.stem,
                page=index + 1,
                index=position,
                extension=extension,
            )
            destination = prepare_output(directory / name, overwrite=overwrite)

            save_options: dict[str, Any] = {}
            if pil_format in ("JPEG", "WEBP"):
                save_options["quality"] = quality
                image = image.convert("L" if grayscale else "RGB")
            image.save(destination, format=pil_format, dpi=(dpi, dpi), **save_options)

            size = destination.stat().st_size
            total_bytes += size
            written.append(destination)
    finally:
        document.close()

    return OperationResult(
        outputs=written,
        pages=len(written),
        summary=(
            f"Rendered {len(written)} page{'s' if len(written) != 1 else ''} to "
            f"{key.upper()} at {dpi} DPI ({human_size(total_bytes)})"
        ),
        input_bytes=source.stat().st_size,
        output_bytes=total_bytes,
        details={"dpi": dpi, "format": key, "directory": str(directory)},
    )


def _render_name(
    template: str, *, stem: str, page: int, index: int, extension: str
) -> str:
    try:
        name = template.format(stem=stem, page=page, index=index, ext=extension)
    except (KeyError, IndexError, ValueError) as exc:
        raise InvalidDocument(
            f"Invalid filename template {template!r}: {exc}\n"
            f"Available fields: stem, page, index, ext."
        ) from exc
    return name if Path(name).suffix else name + extension


# --------------------------------------------------------------------------- #
# images -> PDF
# --------------------------------------------------------------------------- #


def images_to_pdf(
    images: Iterable[str | os.PathLike[str]],
    output: str | os.PathLike[str],
    *,
    page_size: str = "auto",
    margin: float = 0.0,
    dpi: int = 150,
    quality: int = 90,
    overwrite: bool = False,
) -> OperationResult:
    """Assemble images into a single PDF, one image per page.

    Args:
        images: Image files, or directories to take images from. Order is
            preserved; directory contents are sorted naturally so ``img2``
            precedes ``img10``.
        output: Destination PDF.
        page_size: ``"auto"`` sizes each page to its image at ``dpi``.
            Otherwise one of :data:`PAGE_SIZES`, with the image centred and
            scaled to fit.
        margin: Margin in points, when ``page_size`` is a named size.
        dpi: Assumed image resolution, for ``page_size="auto"``.
        quality: JPEG quality used for the embedded rasters.
        overwrite: Allow replacing an existing ``output``.

    Raises:
        InvalidDocument: No usable images were found.
        UnsupportedOperation: Unknown page size.
    """
    Image = require_optional("PIL.Image", "Building PDFs from images", "images")

    size_key = page_size.lower()
    if size_key != "auto" and size_key not in PAGE_SIZES:
        raise UnsupportedOperation(
            f"Unknown page size {page_size!r}. Choose 'auto' or one of: "
            f"{', '.join(sorted(PAGE_SIZES))}."
        )

    sources = _collect_images(images)
    target = prepare_output(output, overwrite=overwrite)

    pages: list[Any] = []
    input_bytes = 0

    for path in sources:
        try:
            with Image.open(path) as handle:
                frame = handle.convert("RGB")
        except Exception as exc:
            raise InvalidDocument(f"Could not read image {path}: {exc}") from exc

        input_bytes += path.stat().st_size
        pages.append(
            frame
            if size_key == "auto"
            else _fit_to_page(Image, frame, PAGE_SIZES[size_key], margin, dpi)
        )

    first, *rest = pages
    first.save(
        target,
        format="PDF",
        save_all=True,
        append_images=rest,
        resolution=float(dpi),
        quality=quality,
    )

    return OperationResult(
        outputs=[target],
        pages=len(pages),
        summary=(
            f"Built {target.name} from {len(pages)} image"
            f"{'s' if len(pages) != 1 else ''} ({size_key} pages)"
        ),
        input_bytes=input_bytes,
        output_bytes=target.stat().st_size,
        details={"page_size": size_key, "dpi": dpi},
    )


def _collect_images(paths: Iterable[str | os.PathLike[str]]) -> list[Path]:
    """Expand files and directories into an ordered list of image paths."""
    collected: list[Path] = []
    for raw in paths:
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            found = sorted(
                (
                    p
                    for p in candidate.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
                ),
                key=lambda p: _natural_key(p.name),
            )
            if not found:
                raise InvalidDocument(f"No image files found in {candidate}")
            collected.extend(found)
        elif not candidate.exists():
            raise InvalidDocument(f"No such file: {candidate}")
        else:
            collected.append(candidate)

    if not collected:
        raise InvalidDocument("No images were given.")
    return collected


def _natural_key(name: str) -> tuple[object, ...]:
    parts: list[object] = []
    digits = ""
    for char in name.lower():
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


def _fit_to_page(
    Image: Any, frame: Any, size_points: tuple[float, float], margin: float, dpi: int
) -> Any:
    """Centre an image on a fixed page, scaled to fit inside the margins."""
    scale = dpi / 72.0
    page_width = int(size_points[0] * scale)
    page_height = int(size_points[1] * scale)
    inset = int(margin * scale)

    usable_width = max(1, page_width - 2 * inset)
    usable_height = max(1, page_height - 2 * inset)

    ratio = min(usable_width / frame.width, usable_height / frame.height)
    new_size = (max(1, int(frame.width * ratio)), max(1, int(frame.height * ratio)))
    resized = frame.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGB", (page_width, page_height), "white")
    canvas.paste(
        resized,
        ((page_width - new_size[0]) // 2, (page_height - new_size[1]) // 2),
    )
    return canvas
