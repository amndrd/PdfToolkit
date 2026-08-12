"""The ``recto`` command-line application.

Commands are grouped into modules under :mod:`recto.cli.commands` and stitched
together here. Every command funnels its failures through :func:`main`, so a
:class:`~recto.errors.RectoError` becomes a clean one-line message and a
meaningful exit code rather than a traceback.
"""

import sys

import typer

from .. import __version__
from ..errors import RectoError
from .commands import basics, images, meta, optimize, pages, security, serve
from .render import console, render_error

app = typer.Typer(
    name="recto",
    help=(
        "A local-first PDF toolkit.\n\n"
        "Merge, split, rotate, extract, compress, encrypt and convert PDFs "
        "entirely on your own machine. No uploads, no accounts, no network.\n\n"
        "Run 'recto serve' for a drag-and-drop interface in your browser."
    ),
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

# The four essentials, then everything else.
app.registered_commands += basics.app.registered_commands
app.registered_commands += pages.app.registered_commands
app.registered_commands += security.app.registered_commands
app.registered_commands += meta.app.registered_commands
app.registered_commands += optimize.app.registered_commands
app.registered_commands += images.app.registered_commands
app.registered_commands += serve.app.registered_commands

app.add_typer(meta.meta_app, name="meta")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"recto {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Shared entry point; per-command options live on the commands."""


def main() -> int:
    """Console-script entry point.

    Turns Recto's own exceptions into tidy one-line messages with meaningful
    exit codes, and makes Ctrl-C behave the way a Unix program should.
    """
    try:
        app(standalone_mode=False)
    except (RectoError, OSError) as error:
        return render_error(error)
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        return 130
    except SystemExit as error:  # a nested parser called sys.exit directly
        return int(error.code or 0)
    except BaseException as error:
        code = _handle_control_flow(error)
        if code is None:
            raise
        return code
    return 0


def _handle_control_flow(error: BaseException) -> int | None:
    """Translate a Click/Typer control-flow exception into an exit code.

    Matching is structural rather than by class, deliberately. Typer vendors
    its own copy of Click, so ``click.exceptions.UsageError`` and the class
    Typer actually raises are two different objects — an ``isinstance`` check
    against the standalone Click would silently never match, and every usage
    error would surface as an unhandled traceback.

    Returns ``None`` when the exception is not control flow, meaning the caller
    should re-raise it.
    """
    name = type(error).__name__

    if name == "Exit":  # typer.Exit / click Exit — a requested, clean stop
        return int(getattr(error, "exit_code", 0) or 0)

    if name == "Abort":  # Ctrl-C or Ctrl-D at a prompt
        console.print("\n[dim]Aborted.[/dim]")
        return 130

    show = getattr(error, "show", None)
    if callable(show):  # UsageError, BadParameter, and friends
        show()
        return int(getattr(error, "exit_code", 1) or 1)

    return None


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
