"""AWS Lambda entry point — Mangum wraps the FastAPI app."""

import os
from pathlib import Path

from mangum import Mangum

from . import create_app
from .storage import get_storage_backend

backend = get_storage_backend()

library_path = Path(os.environ["LIBRARY_PATH"]) if os.environ.get("LIBRARY_PATH") else None

app = create_app(storage_backend=backend, library_path=library_path or Path("aig-library"))
handler = Mangum(app)
