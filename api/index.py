"""Vercel serverless entrypoint: exposes the A2A ASGI application.

Vercel discovers the ASGI `app` object here and routes every request
(including /.well-known/agent-card.json) to it via vercel.json.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rolefit.app import create_app  # noqa: E402

app = create_app(os.environ.get("A2A_BASE_URL"))
