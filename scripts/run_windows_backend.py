"""Run the backend with explicit local settings, including empty credentials."""

import argparse
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
import uvicorn

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
os.chdir(root / "backend")
# Python preserves empty values, so existing backend/.env credentials cannot
# replace the deliberately empty credentials in this local profile.
os.environ.update(
    {k: v for k, v in dotenv_values(root / ".env.local").items() if v is not None}
)
parser = argparse.ArgumentParser()
parser.add_argument("--background-tasks", action="store_true")
args = parser.parse_args()
uvicorn.run(
    "app.main:socket_app",
    host="127.0.0.1",
    port=8000,
    lifespan="on" if args.background_tasks else "off",
)
