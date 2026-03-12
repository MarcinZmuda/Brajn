"""
Brajn SEO — Application Entry Point

Run locally:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
Render.com:   gunicorn main:app -k uvicorn.workers.UvicornWorker
"""
from src.app import app  # noqa: F401 — re-export for gunicorn/uvicorn

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
