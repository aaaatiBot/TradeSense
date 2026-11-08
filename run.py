"""Application entrypoint for local execution and WSGI servers."""
import os
from app import create_app

app = create_app(os.getenv("FLASK_ENV", "development"))

if __name__ == "__main__":
    host = app.config.get("HOST", "127.0.0.1")
    port = app.config.get("PORT", 5000)
    debug = app.config.get("DEBUG", False)
    app.run(host=host, port=port, debug=debug)
