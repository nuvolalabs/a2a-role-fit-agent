"""Run the A2A server: python -m rolefit"""

from __future__ import annotations

import os

import uvicorn

from .app import create_app


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8024"))
    base_url = os.environ.get("A2A_BASE_URL", f"http://{host}:{port}")
    uvicorn.run(create_app(base_url), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
