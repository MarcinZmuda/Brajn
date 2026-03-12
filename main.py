"""
Brajn SEO — Application Entry Point
Run with: uvicorn main:app --host 0.0.0.0 --port $PORT
"""
from src.app import app

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
