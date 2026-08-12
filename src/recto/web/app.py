"""The offline web interface.

Design constraints, in order of importance:

1. **Nothing leaves the machine.** No CDN, no font service, no analytics. The
   single page ships with the package; the CSP below forbids anything else.
2. **Loopback only.** The server refuses requests whose ``Host`` header is not
   local unless the operator explicitly bound elsewhere. This is what stops a
   malicious web page from driving your local Recto through DNS rebinding —
   the browser would happily send those requests otherwise.
3. **The filesystem is not addressable.** Uploads land in a temporary
   workspace under generated ids. No request path is ever joined to a
   user-supplied string.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..core.document import load_pdf
from ..errors import RectoError
from .preview import available as previews_available
from .preview import render_thumbnail
from .tools import catalogue, get_tool

__all__ = ["Workspace", "create_app"]

STATIC_DIR = Path(__file__).parent / "static"

#: Per-file upload ceiling. Generous for PDFs, low enough to bound memory.
MAX_UPLOAD_BYTES = int(os.environ.get("RECTO_MAX_UPLOAD_MB", "512")) * 1024 * 1024

#: Host header values accepted by default.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"})

_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


# --------------------------------------------------------------------------- #
# Workspace
# --------------------------------------------------------------------------- #


@dataclass
class StoredFile:
    """An uploaded file, addressable only by its generated id."""

    id: str
    name: str
    path: Path
    size: int
    pages: int | None = None
    encrypted: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "size": self.size,
            "pages": self.pages,
            "encrypted": self.encrypted,
            "error": self.error,
        }


@dataclass
class Workspace:
    """Temporary storage for one server run.

    Everything lives under a single directory that is removed on shutdown.
    Nothing here persists, and nothing here is reachable by path.
    """

    root: Path
    files: dict[str, StoredFile] = field(default_factory=dict)
    jobs: dict[str, list[Path]] = field(default_factory=dict)

    @classmethod
    def create(cls, root: Path | None = None) -> Workspace:
        base = Path(root) if root else Path(tempfile.mkdtemp(prefix="recto-"))
        (base / "uploads").mkdir(parents=True, exist_ok=True)
        (base / "results").mkdir(parents=True, exist_ok=True)
        return cls(root=base)

    def store(self, filename: str, payload: bytes) -> StoredFile:
        """Save an upload under a generated id, keeping only its basename."""
        file_id = uuid.uuid4().hex
        safe_name = Path(filename or "upload").name or "upload"

        directory = self.root / "uploads" / file_id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / safe_name
        destination.write_bytes(payload)

        stored = StoredFile(
            id=file_id, name=safe_name, path=destination, size=len(payload)
        )
        self._probe(stored)
        self.files[file_id] = stored
        return stored

    def _probe(self, stored: StoredFile) -> None:
        """Fill in page count, so the UI can show it. Never fatal."""
        if stored.path.suffix.lower() != ".pdf":
            return
        try:
            stored.pages = load_pdf(stored.path).page_count
        except RectoError as exc:
            stored.encrypted = type(exc).__name__ in ("PasswordRequired", "WrongPassword")
            stored.error = None if stored.encrypted else str(exc)

    def get(self, file_id: str) -> StoredFile:
        stored = self.files.get(file_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Unknown file id")
        return stored

    def discard(self, file_id: str) -> None:
        stored = self.files.pop(file_id, None)
        if stored is not None:
            shutil.rmtree(stored.path.parent, ignore_errors=True)

    def new_job(self) -> tuple[str, Path]:
        job_id = uuid.uuid4().hex
        directory = self.root / "results" / job_id
        directory.mkdir(parents=True, exist_ok=True)
        return job_id, directory

    def job_file(self, job_id: str, index: int) -> Path:
        outputs = self.jobs.get(job_id)
        if outputs is None or not 0 <= index < len(outputs):
            raise HTTPException(status_code=404, detail="Unknown result")
        return outputs[index]

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #


def create_app(workspace: Path | None = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        workspace: Directory for temporary files. A fresh temporary directory
            is created — and removed on shutdown — when omitted.
    """
    space = Workspace.create(workspace)
    allow_any_host = os.environ.get("RECTO_ALLOW_ANY_HOST") == "1"

    app = FastAPI(
        title="Recto",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.workspace = space

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Refuse non-local callers, and harden every response."""
        if not allow_any_host:
            host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
            if host and host not in {h.strip("[]") for h in LOCAL_HOSTS}:
                return JSONResponse(
                    {
                        "detail": f"Refusing request for host {host!r}. Recto only "
                        f"serves localhost."
                    },
                    status_code=421,
                )

        origin = request.headers.get("origin")
        if origin and not _is_local_origin(origin):
            return JSONResponse(
                {"detail": "Cross-origin requests are not accepted."}, status_code=403
            )

        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RectoError)
    async def handle_recto_error(_: Request, exc: RectoError) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc), "error": type(exc).__name__},
            status_code=400,
        )

    def get_space() -> Workspace:
        return space

    # ---------------------------------------------------------------- routes

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/tools")
    async def tools() -> dict[str, Any]:
        return {
            "tools": catalogue(),
            "version": __version__,
            "previews": previews_available(),
        }

    @app.post("/api/files")
    async def upload(
        files: list[UploadFile] = File(...),
        space: Workspace = Depends(get_space),
    ) -> dict[str, Any]:
        stored: list[dict[str, Any]] = []
        for upload_file in files:
            payload = await upload_file.read()
            if len(payload) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"{upload_file.filename} is larger than the "
                        f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit. Raise it "
                        f"with RECTO_MAX_UPLOAD_MB, or use the command line, "
                        f"which streams from disk."
                    ),
                )
            if not payload:
                raise HTTPException(
                    status_code=400, detail=f"{upload_file.filename} is empty."
                )
            stored.append(
                space.store(upload_file.filename or "upload", payload).to_dict()
            )
        return {"files": stored}

    @app.get("/api/files/{file_id}/page/{page}")
    async def thumbnail(
        file_id: str,
        page: int,
        width: int = 240,
        password: str = "",
        space: Workspace = Depends(get_space),
    ) -> FileResponse:
        """Render one page of an uploaded file as a PNG."""
        stored = space.get(file_id)
        if page < 0:
            raise HTTPException(status_code=404, detail="No such page")

        rendered = render_thumbnail(
            stored.path,
            page,
            width=width,
            cache_dir=space.root / "thumbs" / file_id,
            password=password or None,
        )
        # Thumbnails are immutable for the life of the workspace, and the
        # workspace is discarded on shutdown — so caching them is safe.
        return FileResponse(
            rendered,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.delete("/api/files/{file_id}")
    async def forget(
        file_id: str, space: Workspace = Depends(get_space)
    ) -> dict[str, bool]:
        space.discard(file_id)
        return {"ok": True}

    @app.post("/api/run")
    async def run(
        payload: dict[str, Any], space: Workspace = Depends(get_space)
    ) -> dict[str, Any]:
        tool = get_tool(str(payload.get("tool", "")))
        if tool is None:
            raise HTTPException(status_code=404, detail="Unknown tool")

        file_ids = payload.get("files") or []
        if not isinstance(file_ids, list) or not file_ids:
            raise HTTPException(status_code=400, detail="No files selected.")

        expected = {"one": 1, "two": 2}.get(tool.inputs)
        if expected is not None and len(file_ids) != expected:
            raise HTTPException(
                status_code=400,
                detail=f"{tool.label} needs exactly {expected} file"
                f"{'s' if expected != 1 else ''}, got {len(file_ids)}.",
            )
        if tool.inputs == "many" and len(file_ids) < 2 and tool.id == "merge":
            raise HTTPException(
                status_code=400, detail="Merging needs at least two files."
            )

        paths = [space.get(str(file_id)).path for file_id in file_ids]
        options = payload.get("options") or {}
        if not isinstance(options, dict):
            raise HTTPException(status_code=400, detail="Options must be an object.")

        job_id, out_dir = space.new_job()
        result = tool.run(paths, out_dir, options)
        space.jobs[job_id] = list(result.outputs)

        return {
            "job": job_id,
            "summary": result.summary,
            "pages": result.pages,
            "input_bytes": result.input_bytes,
            "output_bytes": result.output_bytes,
            "size_delta": result.size_delta,
            "details": result.details,
            "outputs": [
                {"name": path.name, "bytes": path.stat().st_size, "index": index}
                for index, path in enumerate(result.outputs)
            ],
        }

    @app.get("/api/result/{job_id}/{index}")
    async def download(
        job_id: str, index: int, space: Workspace = Depends(get_space)
    ) -> FileResponse:
        path = space.job_file(job_id, index)
        return FileResponse(
            path, filename=path.name, media_type="application/octet-stream"
        )

    @app.get("/api/result/{job_id}/archive/all.zip")
    async def download_all(
        job_id: str, space: Workspace = Depends(get_space)
    ) -> Response:
        outputs = space.jobs.get(job_id)
        if not outputs:
            raise HTTPException(status_code=404, detail="Unknown result")

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in outputs:
                archive.write(path, arcname=path.name)
        return Response(
            buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="recto-results.zip"'},
        )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        space.cleanup()

    return app


def _is_local_origin(origin: str) -> bool:
    """True when an ``Origin`` header points back at this machine."""
    from urllib.parse import urlparse

    host = (urlparse(origin).hostname or "").strip("[]")
    return host in {h.strip("[]") for h in LOCAL_HOSTS}
