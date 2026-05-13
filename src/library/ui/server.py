"""Uvicorn server runner for the Library QC UI."""

from pathlib import Path

import uvicorn

from . import create_app


def run(
    db_path: Path,
    library_path: Path = Path("aig-library"),
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Create the FastAPI app and start the uvicorn server.

    Args:
        db_path: Path to the library database directory.
        library_path: Path to the AIG library directory.
        host: Host address to bind to.
        port: Port number to listen on.
    """
    app = create_app(db_path=db_path, library_path=library_path)
    uvicorn.run(app, host=host, port=port)
