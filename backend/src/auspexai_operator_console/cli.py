"""Click CLI for `auspexai-operator-console`."""

from __future__ import annotations

import click
import uvicorn

from . import __version__
from .config import OperatorConsoleConfig


@click.group(help="AuspexAI operator console (Phase 2 closed-beta maintainer dashboard).")
@click.version_option(version=__version__, prog_name="auspexai-operator-console")
def cli() -> None:
    pass


@cli.command()
@click.option("--host", default=None, help="Bind host (default: 127.0.0.1 or $HOST).")
@click.option("--port", default=None, type=int, help="Bind port (default: 4227 or $PORT).")
@click.option("--reload", is_flag=True, help="Reload on source changes (dev only).")
def serve(host: str | None, port: int | None, reload: bool) -> None:
    """Run the operator console HTTP server (factory pattern for slowapi-friendly future)."""
    config = OperatorConsoleConfig.from_env()
    bind_host = host or config.bind_host
    bind_port = port or config.bind_port
    uvicorn.run(
        "auspexai_operator_console.main:create_app",
        factory=True,
        host=bind_host,
        port=bind_port,
        reload=reload,
        log_level="info",
    )


def main() -> None:
    cli(prog_name="auspexai-operator-console")


if __name__ == "__main__":
    main()
