"""Compatibility shim so `uvicorn app:app` works.

If the server is launched with an entrypoint of `app:app`, reuse the FastAPI
instance defined in main.py. This avoids ModuleNotFoundError during reload on
Windows when the app string is mis-specified.
"""

from main import app  # noqa: F401
