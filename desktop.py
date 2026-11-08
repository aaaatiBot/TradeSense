"""TradeSense Desktop Application Launcher
Starts the local server, initializes the database, and automatically launches your browser.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

# Ensure root directory is on Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.services.disclaimer_service import DisclaimerService

PORT = 5000
URL = f"http://localhost:{PORT}/dashboard"


def open_browser():
    """Wait for server initialization then open the user's default browser."""
    time.sleep(1.5)
    print(f"\n[+] Opening TradeSense in your browser: {URL}\n")
    webbrowser.open(URL)


def main():
    print("=" * 60)
    print("  TradeSense: Educational Stock-Advisory Simulation App")
    print("  SEBI Compliant | Cryptographic Ledger | Soft UI")
    print("=" * 60)
    print("[*] Initializing local database and statutory disclaimers...")

    app = create_app("development")

    with app.app_context():
        db.create_all()
        DisclaimerService.seed_disclaimers()

    print("[*] Starting local application server on port 5000...")
    threading.Thread(target=open_browser, daemon=True).start()

    try:
        app.run(host="127.0.0.1", port=PORT, debug=False)
    except KeyboardInterrupt:
        print("\n[*] TradeSense stopped safely. Goodbye!")


if __name__ == "__main__":
    main()
