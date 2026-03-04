"""ASGI entrypoint wrapper so `uvicorn app.main:app` works.

It simply re-exports the FastAPI instance defined in the project root `main.py`.
"""

from main import app  # noqa: F401
