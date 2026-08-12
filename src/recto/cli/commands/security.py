"""Password and permission commands."""

from pathlib import Path

import typer

from ...core.security import ALGORITHMS, PERMISSIONS
from ...core.security import decrypt as core_decrypt
from ...core.security import encrypt as core_encrypt
from .. import options as opt
from ..render import render_result

app = typer.Typer()

_PERMISSION_HELP = (
    "Comma-separated permissions to grant: "
    + ", ".join(sorted(PERMISSIONS))
    + ". Also accepts 'all' and 'none'."
)


@app.command()
def encrypt(
    input_path: Path = opt.InputFile,
    output: Path | None = opt.OutputFile,
    user_password: str = typer.Option(
        ...,
        "--user-password",
        "-u",
        prompt="Password to open the document",
        hide_input=True,
        confirmation_prompt=True,
        show_default=False,
        help="Required to open the document. Prompted for if omitted.",
    ),
    owner_password: str | None = typer.Option(
        None,
        "--owner-password",
        show_default=False,
        help="Lifts the permission restrictions. Defaults to the user password.",
    ),
    allow: str = typer.Option("all", "--allow", metavar="LIST", help=_PERMISSION_HELP),
    algorithm: str = typer.Option(
        "AES-256",
        "--algorithm",
        metavar="NAME",
        help="One of: " + ", ".join(ALGORITHMS) + ". Only AES-256 is genuinely strong.",
    ),
    password: str | None = opt.Password,
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Protect a document with a password.

        recto encrypt tax-return.pdf -o protected.pdf
        recto encrypt report.pdf -u hunter2 --allow print,copy -o locked.pdf

    Only the user password actually encrypts. The permission flags are
    advisory — any reader is free to ignore them.
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core_encrypt(
        input_path,
        destination,
        user_password,
        owner_password=owner_password,
        allow=opt.parse_csv(allow) or ["all"],
        algorithm=algorithm.upper(),
        password=password,
        overwrite=overwrite,
    )
    render_result(result, as_json=as_json, quiet=quiet)


@app.command()
def decrypt(
    input_path: Path = opt.InputFile,
    output: Path | None = opt.OutputFile,
    password: str = typer.Option(
        ...,
        "--password",
        prompt="Password",
        hide_input=True,
        show_default=False,
        help="The document's current password. Prompted for if omitted.",
    ),
    in_place: bool = opt.InPlace,
    force: bool = opt.Force,
    as_json: bool = opt.AsJson,
    quiet: bool = opt.Quiet,
) -> None:
    """Write an unencrypted copy, given the password.

        recto decrypt statement.pdf -o open.pdf

    Recto does not crack passwords — you need the real one.
    """
    destination, overwrite = opt.resolve_output(input_path, output, in_place, force)
    result = core_decrypt(input_path, destination, password=password, overwrite=overwrite)
    render_result(result, as_json=as_json, quiet=quiet)
