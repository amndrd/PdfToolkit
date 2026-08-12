"""The ``serve`` command: start the offline web UI."""

import threading
import webbrowser

import typer

from ...core.document import require_optional
from ..render import console

app = typer.Typer()


@app.command()
def serve(
    port: int = typer.Option(8765, "--port", metavar="N", help="Port to listen on."),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        metavar="ADDR",
        help=(
            "Interface to bind. The default is loopback-only. Change it and "
            "anyone on your network can read and write files through the UI."
        ),
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Do not open a browser window."
    ),
    reload: bool = typer.Option(
        False, "--reload", help="Restart on code changes (for development)."
    ),
) -> None:
    """Start the local web interface.

        recto serve
        recto serve --port 9000 --no-browser

    Files are processed in a temporary directory on this machine and nothing
    is ever sent anywhere. The server binds to loopback only unless you
    override --host.
    """
    uvicorn = require_optional("uvicorn", "The web interface", "web")
    require_optional("fastapi", "The web interface", "web")

    url = f"http://{'localhost' if host == '127.0.0.1' else host}:{port}"

    if host not in ("127.0.0.1", "localhost", "::1"):
        console.print(
            f"[warn]![/warn] Binding to {host}, not loopback. Anyone who can "
            f"reach this machine on port {port} can use the UI to read and "
            f"write files as you."
        )

    console.print(f"[ok]▸[/ok] Recto is running at [bold]{url}[/bold]")
    console.print("[dim]  Everything stays on this machine. Ctrl-C to stop.[/dim]")

    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        "recto.web.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_level="warning",
    )
