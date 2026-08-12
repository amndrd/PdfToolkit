"""Shrinking and repairing PDFs, via qpdf (through pikepdf).

Where the bytes actually go
---------------------------
In most real documents, embedded raster images dominate the file size and the
page content streams are noise by comparison. So there are two independent
levers, and Recto exposes them separately:

* **Structural** (always safe, always lossless) — recompress streams, pack
  objects into object streams, drop duplicate and orphaned objects. Typically
  saves 5-20% on a text document and almost nothing on a scan.
* **Images** (lossy, opt-in) — re-encode embedded rasters as JPEG at a chosen
  quality, optionally downsampling anything above a target DPI. This is where
  a 40 MB scan becomes a 3 MB one.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

from ..errors import InvalidDocument
from .document import human_size, prepare_output, require_optional
from .result import OperationResult

__all__ = ["optimize", "repair"]

#: Images below this pixel count are left alone — re-encoding costs more in
#: JPEG header overhead than it saves.
_MIN_PIXELS = 10_000


def _open_pikepdf(path: str | os.PathLike[str], password: str | None) -> Any:
    pikepdf = require_optional("pikepdf", "Optimising and repairing PDFs", "optimize")
    try:
        return pikepdf.open(
            str(path), password=password or "", allow_overwriting_input=True
        )
    except pikepdf.PasswordError as exc:
        from ..errors import PasswordRequired, WrongPassword

        if password:
            raise WrongPassword(f"The password for {path} was rejected.") from exc
        raise PasswordRequired(
            f"{path} is password-protected. Supply one with --password."
        ) from exc
    except pikepdf.PdfError as exc:
        raise InvalidDocument(f"Could not open {path}: {exc}") from exc


def optimize(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    image_quality: int | None = None,
    max_dpi: int | None = None,
    linearize: bool = False,
    strip_metadata: bool = False,
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Rewrite a document as compactly as the chosen settings allow.

    Args:
        input_path: Source document.
        output: Destination path.
        image_quality: JPEG quality (1-100) for embedded images. ``None``
            leaves images untouched, keeping the whole operation lossless.
            75 is a good default for scans; below 50 shows visible artefacts.
        max_dpi: Downsample images whose effective resolution exceeds this.
            Requires ``image_quality``. 150 suits screen reading, 300 print.
        linearize: Produce a "fast web view" file, whose first page can be
            displayed before the rest has downloaded. Slightly larger.
        strip_metadata: Also drop the info dictionary and XMP packet.
        password: Password for an encrypted source.
        overwrite: Allow replacing an existing ``output``.

    Returns:
        An :class:`OperationResult` whose ``details`` records how many images
        were re-encoded and the resulting size change.

    Raises:
        InvalidDocument: ``image_quality`` is outside 1-100, or ``max_dpi`` was
            given without it.
    """
    pikepdf = require_optional("pikepdf", "Optimising PDFs", "optimize")

    if image_quality is not None and not 1 <= image_quality <= 100:
        raise InvalidDocument(
            f"--image-quality must be between 1 and 100, got {image_quality}."
        )
    if max_dpi is not None and image_quality is None:
        raise InvalidDocument(
            "--max-dpi only applies when re-encoding images; pass "
            "--image-quality too (e.g. --image-quality 75 --max-dpi 150)."
        )

    source = Path(input_path).expanduser()
    original_bytes = source.stat().st_size
    target = prepare_output(output, overwrite=overwrite)

    pdf = _open_pikepdf(source, password)
    with pdf:
        recompressed = 0
        if image_quality is not None:
            recompressed = _recompress_images(pdf, image_quality, max_dpi)

        if strip_metadata:
            with pdf.open_metadata() as meta:
                meta.clear()
            pdf.trailer.get("/Info") and pdf.trailer.__delitem__("/Info")

        pdf.remove_unreferenced_resources()
        pdf.save(
            str(target),
            linearize=linearize,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            normalize_content=False,
        )

    final_bytes = target.stat().st_size
    saved = original_bytes - final_bytes
    percent = (saved / original_bytes * 100) if original_bytes else 0.0

    if saved > 0:
        headline = f"Saved {human_size(saved)} ({percent:.0f}% smaller)"
    else:
        headline = (
            f"No size reduction ({human_size(-saved)} larger) — this file was "
            f"already well compressed"
        )

    return OperationResult(
        outputs=[target],
        pages=0,
        summary=f"{headline}: {human_size(original_bytes)} -> {human_size(final_bytes)}",
        input_bytes=original_bytes,
        output_bytes=final_bytes,
        details={
            "images_recompressed": recompressed,
            "lossless": image_quality is None,
            "linearized": linearize,
            "bytes_saved": saved,
        },
    )


def _recompress_images(pdf: Any, quality: int, max_dpi: int | None) -> int:
    """Re-encode embedded rasters as JPEG. Returns how many were replaced.

    Conservative by design — an image is skipped when re-encoding would be
    wrong (transparency, bilevel scans, indexed palettes) or pointless (the
    JPEG comes out no smaller than what was already there).
    """
    pikepdf = require_optional("pikepdf", "Optimising PDFs", "optimize")
    require_optional("PIL", "Re-encoding embedded images", "images")

    replaced = 0
    for page in pdf.pages:
        try:
            images = dict(page.images)
        except Exception:  # pragma: no cover - page without resources
            continue

        for name, raw in images.items():
            new_stream = _rebuild_image(pdf, pikepdf, page, raw, quality, max_dpi)
            if new_stream is None:
                continue
            try:
                page.Resources.XObject[name] = new_stream
                replaced += 1
            except Exception:  # pragma: no cover - inherited resource dict
                continue
    return replaced


def _rebuild_image(
    pdf: Any, pikepdf: Any, page: Any, raw: Any, quality: int, max_dpi: int | None
) -> Any | None:
    """Return a smaller JPEG replacement for ``raw``, or None to keep it."""
    # Transparency cannot survive a JPEG round-trip.
    if "/SMask" in raw or "/Mask" in raw:
        return None
    # Bilevel scans (CCITT/JBIG2) get dramatically *larger* as JPEG.
    if int(raw.get("/BitsPerComponent", 8) or 8) < 8:
        return None

    try:
        pil = pikepdf.PdfImage(raw).as_pil_image()
    except Exception:
        return None  # unsupported codec — leave it exactly as it was

    if pil.width * pil.height < _MIN_PIXELS:
        return None

    if max_dpi:
        pil = _downsample(pil, page, max_dpi)

    try:
        original_size = len(raw.read_raw_bytes())
    except Exception:
        original_size = 0

    buffer = io.BytesIO()
    pil.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    payload = buffer.getvalue()

    # Never trade quality for nothing.
    if original_size and len(payload) >= original_size * 0.95:
        return None

    stream = pikepdf.Stream(pdf, payload)
    stream.Type = pikepdf.Name.XObject
    stream.Subtype = pikepdf.Name.Image
    stream.Width = pil.width
    stream.Height = pil.height
    stream.ColorSpace = pikepdf.Name.DeviceRGB
    stream.BitsPerComponent = 8
    stream.Filter = pikepdf.Name.DCTDecode
    return stream


def _downsample(pil: Any, page: Any, max_dpi: int) -> Any:
    """Shrink an image whose resolution exceeds ``max_dpi`` on the page."""
    Image = require_optional("PIL.Image", "Downsampling images", "images")
    try:
        box = page.mediabox
        width_inches = float(box[2] - box[0]) / 72.0
    except Exception:
        return pil

    if width_inches <= 0:
        return pil

    effective_dpi = pil.width / width_inches
    if effective_dpi <= max_dpi:
        return pil

    factor = max_dpi / effective_dpi
    new_size = (max(1, int(pil.width * factor)), max(1, int(pil.height * factor)))
    return pil.resize(new_size, Image.LANCZOS)


def repair(
    input_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    password: str | None = None,
    overwrite: bool = False,
) -> OperationResult:
    """Rebuild a damaged PDF's cross-reference table and object structure.

    qpdf can recover files that other tools refuse to open — truncated
    downloads, broken xref tables, malformed object streams. Content that was
    genuinely lost stays lost; this recovers what is still in the file.
    """
    source = Path(input_path).expanduser()
    if not source.exists():
        raise InvalidDocument(f"No such file: {source}")

    original_bytes = source.stat().st_size
    target = prepare_output(output, overwrite=overwrite)

    pdf = _open_pikepdf(source, password)
    with pdf:
        pages = len(pdf.pages)
        pdf.save(str(target), fix_metadata_version=True)

    return OperationResult(
        outputs=[target],
        pages=pages,
        summary=f"Rebuilt {source.name} ({pages} pages recovered)",
        input_bytes=original_bytes,
        output_bytes=target.stat().st_size,
    )
