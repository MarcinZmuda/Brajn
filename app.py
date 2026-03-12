"""
Brajn SEO — Compatibility entry point for gunicorn.

Gunicorn (WSGI) cannot serve FastAPI (ASGI) directly.
Use uvicorn workers: gunicorn app:app -k uvicorn.workers.UvicornWorker

This file re-exports from main.py for backwards compatibility with
Render dashboard configs that reference app:app.
"""
from main import app  # noqa: F401
