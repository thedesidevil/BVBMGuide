"""FastAPI application factory for the Library QC UI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import tree, city, country, review, sweep, audit, ingest


def create_app(db_path: Path, library_path: Path = Path("aig-library")) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Path to the library database directory.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Library QC UI",
        description="Quality control interface for the AIG library database",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.db_path = db_path
    app.state.library_path = library_path

    app.include_router(tree.router, prefix="/api")
    app.include_router(city.router, prefix="/api")
    app.include_router(country.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(sweep.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")

    # Serve built frontend if it exists (must come last so API routes take priority)
    from fastapi.staticfiles import StaticFiles

    dist_path = Path(__file__).parent.parent.parent.parent / "ui-frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")

    return app
