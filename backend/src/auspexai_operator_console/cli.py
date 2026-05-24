"""Click CLI for `auspexai-operator-console`."""

from __future__ import annotations

from pathlib import Path

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


@cli.command("set-passphrase")
@click.option(
    "--store-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Encrypted-file backend path (default: /var/lib/auspexai-operator-console/passphrase.enc).",
)
def set_passphrase(store_path: Path | None) -> None:
    """Set the operator passphrase for the rage-shell second factor.

    Stores in GNOME Keyring (Secret Service) when available, otherwise in
    a ChaCha20-Poly1305-encrypted file tied to this host's machine-id + uid.
    """
    import getpass
    import sys

    from .passphrase_store import PassphraseStoreError, default_store

    enc_path = store_path or Path("/var/lib/auspexai-operator-console/passphrase.enc")
    click.echo(f"Initialising passphrase store (encrypted-file path: {enc_path}) …")
    try:
        store = default_store(encrypted_file_path=enc_path)
    except PassphraseStoreError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Backend: {store.backend_name()}")

    if store.has_passphrase():
        click.echo("A passphrase already exists.")
        if not click.confirm("Overwrite it?"):
            raise SystemExit(0)

    if sys.stdin.isatty():
        passphrase = getpass.getpass("Operator passphrase: ")
        confirm = getpass.getpass("Confirm passphrase: ")
    else:
        click.echo("Reading passphrase from stdin (two lines: passphrase, then confirm).")
        passphrase = sys.stdin.readline().rstrip("\n")
        confirm = sys.stdin.readline().rstrip("\n")

    if passphrase != confirm:
        raise click.ClickException("Passphrases do not match.")
    if len(passphrase) < 8:
        raise click.ClickException("Passphrase must be at least 8 characters.")

    try:
        store.store(passphrase)
    except PassphraseStoreError as exc:
        raise click.ClickException(f"Failed to store passphrase: {exc}") from exc

    click.echo(f"Passphrase stored in {store.backend_name()}.")


def main() -> None:
    cli(prog_name="auspexai-operator-console")


if __name__ == "__main__":
    main()
