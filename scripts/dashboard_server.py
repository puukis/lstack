"""Launcher shim — delegates to dashboard/backend/server.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.backend.server import main

if __name__ == "__main__":
    main()
