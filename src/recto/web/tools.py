"""The tool registry that drives the web UI.

The browser does not know what a "split" is. It asks ``GET /api/tools``, gets
the declarations below, and renders a form from them. Adding a tool to the web
interface therefore means adding one entry here — no HTML, no JavaScript.

That also means the form the user sees and the arguments the server accepts
cannot drift apart: they are generated from the same object.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Imported as functions rather than modules: in ``recto.core`` the names
# ``merge``, ``split``, ``rotate``, ``extract`` and ``optimize`` are the
# operations themselves, which shadow the submodules of the same name.
from ..core.extract import extract as _extract
from ..core.images import images_to_pdf as _images_to_pdf
from ..core.images import pdf_to_images as _pdf_to_images
from ..core.merge import merge as _merge
from ..core.metadata import set_metadata as _set_metadata
from ..core.metadata import strip_metadata as _strip_metadata
from ..core.optimize import optimize as _optimize
from ..core.optimize import repair as _repair
from ..core.pages import delete as _delete
from ..core.pages import duplicate as _duplicate
from ..core.pages import insert as _insert
from ..core.pages import reorder as _reorder
from ..core.pages import reverse as _reverse
from ..core.result import OperationResult
from ..core.rotate import rotate as _rotate
from ..core.security import ALGORITHMS, PERMISSIONS
from ..core.security import decrypt as _decrypt
from ..core.security import encrypt as _encrypt
from ..core.split import split as _split

__all__ = ["TOOLS", "Field", "Tool", "catalogue", "get_tool"]

FieldKind = Literal[
    "pages", "text", "number", "bool", "select", "multiselect", "password"
]


@dataclass(slots=True)
class Field:
    """One form control, and the option it fills in."""

    name: str
    kind: FieldKind
    label: str
    default: Any = None
    choices: Sequence[str] | None = None
    help: str = ""
    required: bool = False
    minimum: int | None = None
    maximum: int | None = None
    #: Only show this control when another field has one of these values.
    when: Mapping[str, Sequence[str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "default": self.default,
            "choices": list(self.choices) if self.choices else None,
            "help": self.help,
            "required": self.required,
            "min": self.minimum,
            "max": self.maximum,
            "when": {k: list(v) for k, v in self.when.items()} if self.when else None,
        }


@dataclass(slots=True)
class Tool:
    """A operation exposed in the web UI."""

    id: str
    label: str
    description: str
    group: str
    #: How many input files: exactly one, exactly two, or any number.
    inputs: Literal["one", "two", "many"]
    #: What the inputs are.
    accepts: Literal["pdf", "image"] = "pdf"
    fields: list[Field] = field(default_factory=list)
    #: Called as ``run(paths, out_dir, options)``.
    run: Callable[[list[Path], Path, dict[str, Any]], OperationResult] = None  # type: ignore[assignment]
    #: Label for the second input slot, when ``inputs == "two"``.
    second_label: str = "Second file"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "group": self.group,
            "inputs": self.inputs,
            "accepts": self.accepts,
            "second_label": self.second_label,
            "fields": [f.to_dict() for f in self.fields],
        }


# --------------------------------------------------------------------------- #
# Shared field definitions
# --------------------------------------------------------------------------- #


def _pages(required: bool = False, name: str = "pages", label: str = "Pages") -> Field:
    return Field(
        name=name,
        kind="pages",
        label=label,
        required=required,
        help="e.g. 1-3,7 · 2- · -5 · last · odd · even. Blank means every page.",
    )


_PASSWORD = Field(
    name="password",
    kind="password",
    label="Input password",
    help="Only if the source file is encrypted.",
)


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #


def _out(out_dir: Path, name: str) -> Path:
    return out_dir / name


def _run_merge(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _merge(
        paths,
        _out(out_dir, "merged.pdf"),
        password=options.get("password") or None,
        outline=not options.get("no_outline"),
        overwrite=True,
    )


def _run_split(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    mode = options.get("mode") or "every"
    raw_ranges = str(options.get("ranges") or "").strip()
    return _split(
        paths[0],
        out_dir,
        mode=mode,  # type: ignore[arg-type]
        every=_int(options.get("every")),
        into=_int(options.get("into")),
        at=options.get("at") or None,
        ranges=[r.strip() for r in raw_ranges.split(",") if r.strip()] or None,
        outline_depth=_int(options.get("outline_depth")) or 1,
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_rotate(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _rotate(
        paths[0],
        _out(out_dir, paths[0].name),
        _int(options.get("degrees")) or 0,
        pages=options.get("pages") or None,
        absolute=bool(options.get("absolute")),
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_extract(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _extract(
        paths[0],
        _out(out_dir, paths[0].name),
        options.get("pages") or "all",
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_delete(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _delete(
        paths[0],
        _out(out_dir, paths[0].name),
        options.get("pages") or "",
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_reorder(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _reorder(
        paths[0],
        _out(out_dir, paths[0].name),
        options.get("order") or "all",
        keep_unlisted=bool(options.get("keep_unlisted")),
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_reverse(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _reverse(
        paths[0],
        _out(out_dir, paths[0].name),
        pages=options.get("pages") or None,
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_insert(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _insert(
        paths[0],
        paths[1],
        _out(out_dir, paths[0].name),
        at=_int(options.get("at")),
        pages=options.get("pages") or None,
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_duplicate(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _duplicate(
        paths[0],
        _out(out_dir, paths[0].name),
        options.get("pages") or "",
        times=_int(options.get("times")) or 1,
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_encrypt(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    allow = options.get("allow") or ["all"]
    if isinstance(allow, str):
        allow = [a.strip() for a in allow.split(",") if a.strip()]
    return _encrypt(
        paths[0],
        _out(out_dir, paths[0].name),
        str(options.get("user_password") or ""),
        owner_password=options.get("owner_password") or None,
        allow=allow,
        algorithm=str(options.get("algorithm") or "AES-256"),
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_decrypt(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _decrypt(
        paths[0],
        _out(out_dir, paths[0].name),
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_meta_set(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    updates = {
        name: options[name]
        for name in ("title", "author", "subject", "keywords")
        if options.get(name) is not None and str(options.get(name)).strip() != ""
    }
    return _set_metadata(
        paths[0],
        _out(out_dir, paths[0].name),
        updates,
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_meta_strip(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _strip_metadata(
        paths[0],
        _out(out_dir, paths[0].name),
        keep_producer=bool(options.get("keep_producer")),
        password=options.get("password") or None,
        overwrite=True,
    )


_PRESETS = {
    "lossless": (None, None),
    "screen": (60, 100),
    "ebook": (75, 150),
    "print": (85, 300),
}


def _run_compress(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    quality, dpi = _PRESETS.get(str(options.get("preset") or "lossless"), (None, None))
    return _optimize(
        paths[0],
        _out(out_dir, paths[0].name),
        image_quality=quality,
        max_dpi=dpi,
        linearize=bool(options.get("linearize")),
        strip_metadata=bool(options.get("strip_metadata")),
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_repair(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _repair(
        paths[0],
        _out(out_dir, paths[0].name),
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_to_images(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _pdf_to_images(
        paths[0],
        out_dir,
        dpi=_int(options.get("dpi")) or 150,
        fmt=str(options.get("format") or "png"),
        pages=options.get("pages") or None,
        grayscale=bool(options.get("grayscale")),
        password=options.get("password") or None,
        overwrite=True,
    )


def _run_from_images(
    paths: list[Path], out_dir: Path, options: dict[str, Any]
) -> OperationResult:
    return _images_to_pdf(
        paths,
        _out(out_dir, "images.pdf"),
        page_size=str(options.get("page_size") or "auto"),
        margin=float(options.get("margin") or 0),
        dpi=_int(options.get("dpi")) or 150,
        overwrite=True,
    )


def _int(value: Any) -> int | None:
    """Coerce a form value to an int, treating blanks as absent."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #

TOOLS: tuple[Tool, ...] = (
    Tool(
        id="merge",
        label="Merge",
        description="Combine several PDFs into one, in the order shown.",
        group="Essentials",
        inputs="many",
        fields=[
            Field("no_outline", "bool", "Skip per-file bookmarks", default=False),
            _PASSWORD,
        ],
        run=_run_merge,
    ),
    Tool(
        id="split",
        label="Split",
        description="Break one PDF into several.",
        group="Essentials",
        inputs="one",
        fields=[
            Field(
                "mode",
                "select",
                "Strategy",
                default="every",
                choices=["every", "into", "at", "ranges", "outline"],
                help="every: fixed chunks · into: N parts · at: cut points · "
                "ranges: explicit · outline: per bookmark",
            ),
            Field(
                "every",
                "number",
                "Pages per file",
                default=10,
                minimum=1,
                when={"mode": ["every"]},
            ),
            Field(
                "into",
                "number",
                "Number of parts",
                default=2,
                minimum=1,
                when={"mode": ["into"]},
            ),
            Field(
                "at",
                "pages",
                "Cut before pages",
                default="",
                help="e.g. 5,20 gives 1-4, 5-19, 20-end",
                when={"mode": ["at"]},
            ),
            Field(
                "ranges",
                "text",
                "Ranges",
                default="",
                help="Comma-separated, one file each: 1-3, 10-",
                when={"mode": ["ranges"]},
            ),
            Field(
                "outline_depth",
                "number",
                "Bookmark depth",
                default=1,
                minimum=1,
                when={"mode": ["outline"]},
            ),
            _PASSWORD,
        ],
        run=_run_split,
    ),
    Tool(
        id="rotate",
        label="Rotate",
        description="Turn pages a quarter-turn at a time. Lossless.",
        group="Essentials",
        inputs="one",
        fields=[
            Field(
                "degrees",
                "select",
                "Rotation",
                default="90",
                choices=["90", "180", "270", "-90"],
            ),
            _pages(),
            Field(
                "absolute",
                "bool",
                "Set instead of add",
                default=False,
                help="Straightens pages that currently disagree.",
            ),
            _PASSWORD,
        ],
        run=_run_rotate,
    ),
    Tool(
        id="extract",
        label="Extract",
        description="Pull selected pages into a new PDF. Order is honoured.",
        group="Essentials",
        inputs="one",
        fields=[_pages(required=True), _PASSWORD],
        run=_run_extract,
    ),
    Tool(
        id="delete",
        label="Delete pages",
        description="Remove the selected pages.",
        group="Pages",
        inputs="one",
        fields=[_pages(required=True), _PASSWORD],
        run=_run_delete,
    ),
    Tool(
        id="reorder",
        label="Reorder",
        description="Rearrange pages into an explicit order.",
        group="Pages",
        inputs="one",
        fields=[
            Field(
                "order",
                "pages",
                "New order",
                required=True,
                default="",
                help="e.g. 3,1,2 or last,1-3",
            ),
            Field(
                "keep_unlisted", "bool", "Keep unlisted pages at the end", default=False
            ),
            _PASSWORD,
        ],
        run=_run_reorder,
    ),
    Tool(
        id="reverse",
        label="Reverse",
        description="Reverse page order, wholly or within a selection.",
        group="Pages",
        inputs="one",
        fields=[_pages(), _PASSWORD],
        run=_run_reverse,
    ),
    Tool(
        id="insert",
        label="Insert",
        description="Splice one document into another.",
        group="Pages",
        inputs="two",
        second_label="Document to insert",
        fields=[
            Field(
                "at",
                "number",
                "Insert before page",
                default=None,
                minimum=1,
                help="Leave blank to append at the end.",
            ),
            _pages(label="Pages to take from the second file"),
            _PASSWORD,
        ],
        run=_run_insert,
    ),
    Tool(
        id="duplicate",
        label="Duplicate",
        description="Repeat selected pages in place.",
        group="Pages",
        inputs="one",
        fields=[
            _pages(required=True),
            Field("times", "number", "Extra copies", default=1, minimum=1),
            _PASSWORD,
        ],
        run=_run_duplicate,
    ),
    Tool(
        id="encrypt",
        label="Encrypt",
        description="Protect a document with a password.",
        group="Security",
        inputs="one",
        fields=[
            Field("user_password", "password", "Password to open", required=True),
            Field(
                "owner_password",
                "password",
                "Owner password",
                help="Lifts the restrictions below. Defaults to the password above.",
            ),
            Field(
                "allow",
                "multiselect",
                "Permissions granted",
                choices=sorted(PERMISSIONS),
                default=sorted(PERMISSIONS),
            ),
            Field(
                "algorithm",
                "select",
                "Algorithm",
                default="AES-256",
                choices=list(ALGORITHMS),
                help="Only AES-256 is genuinely strong; the others exist for old readers.",
            ),
            _PASSWORD,
        ],
        run=_run_encrypt,
    ),
    Tool(
        id="decrypt",
        label="Decrypt",
        description="Write an unencrypted copy. Needs the real password.",
        group="Security",
        inputs="one",
        fields=[Field("password", "password", "Password", required=True)],
        run=_run_decrypt,
    ),
    Tool(
        id="meta-set",
        label="Edit metadata",
        description="Set title, author, subject and keywords.",
        group="Security",
        inputs="one",
        fields=[
            Field("title", "text", "Title"),
            Field("author", "text", "Author"),
            Field("subject", "text", "Subject"),
            Field("keywords", "text", "Keywords"),
            _PASSWORD,
        ],
        run=_run_meta_set,
    ),
    Tool(
        id="meta-strip",
        label="Strip metadata",
        description="Remove the info dictionary and the XMP packet.",
        group="Security",
        inputs="one",
        fields=[
            Field("keep_producer", "bool", "Leave a Recto producer line", default=False),
            _PASSWORD,
        ],
        run=_run_meta_strip,
    ),
    Tool(
        id="compress",
        label="Compress",
        description="Make a PDF smaller.",
        group="Optimise",
        inputs="one",
        fields=[
            Field(
                "preset",
                "select",
                "Preset",
                default="lossless",
                choices=list(_PRESETS),
                help="lossless keeps every pixel. The others re-encode images.",
            ),
            Field("linearize", "bool", "Optimise for web viewing", default=False),
            Field("strip_metadata", "bool", "Drop metadata too", default=False),
            _PASSWORD,
        ],
        run=_run_compress,
    ),
    Tool(
        id="repair",
        label="Repair",
        description="Rebuild a damaged PDF so other tools will open it.",
        group="Optimise",
        inputs="one",
        fields=[_PASSWORD],
        run=_run_repair,
    ),
    Tool(
        id="to-images",
        label="PDF to images",
        description="Render pages to PNG, JPEG, TIFF or WebP.",
        group="Convert",
        inputs="one",
        fields=[
            Field(
                "format",
                "select",
                "Format",
                default="png",
                choices=["png", "jpeg", "tiff", "webp"],
            ),
            Field(
                "dpi", "number", "Resolution (DPI)", default=150, minimum=12, maximum=1200
            ),
            _pages(),
            Field("grayscale", "bool", "Grayscale", default=False),
            _PASSWORD,
        ],
        run=_run_to_images,
    ),
    Tool(
        id="from-images",
        label="Images to PDF",
        description="Assemble images into a PDF, one image per page.",
        group="Convert",
        inputs="many",
        accepts="image",
        fields=[
            Field(
                "page_size",
                "select",
                "Page size",
                default="auto",
                choices=["auto", "a3", "a4", "a5", "letter", "legal"],
            ),
            Field(
                "margin",
                "number",
                "Margin (points)",
                default=0,
                minimum=0,
                when={"page_size": ["a3", "a4", "a5", "letter", "legal"]},
            ),
            Field("dpi", "number", "Assumed image DPI", default=150, minimum=12),
        ],
        run=_run_from_images,
    ),
)

_BY_ID = {tool.id: tool for tool in TOOLS}


def get_tool(tool_id: str) -> Tool | None:
    """Look a tool up by id."""
    return _BY_ID.get(tool_id)


def catalogue() -> list[dict[str, Any]]:
    """The registry as JSON, for ``GET /api/tools``."""
    return [tool.to_dict() for tool in TOOLS]
