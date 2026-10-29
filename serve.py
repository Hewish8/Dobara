"""Production server: python serve.py  (listens on 0.0.0.0:8000 by default)."""
import os

from waitress import serve

from app import app

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Dobara is running on http://{host}:{port}  (admin at /admin)")
    serve(app, host=host, port=port)
