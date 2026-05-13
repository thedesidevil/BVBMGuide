"""FastAPI application factory for the Library QC UI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import tree, city, country, review, sweep, audit


def create_app(db_path: Path) -> FastAPI:
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

    app.include_router(tree.router, prefix="/api/tree", tags=["tree"])
    app.include_router(city.router, prefix="/api/city", tags=["city"])
    app.include_router(country.router, prefix="/api/country", tags=["country"])
    app.include_router(review.router, prefix="/api/review", tags=["review"])
    app.include_router(sweep.router, prefix="/api/sweep", tags=["sweep"])
    app.include_router(audit.router, prefix="/api/audit", tags=["audit"])

    return app
