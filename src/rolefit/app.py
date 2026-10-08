"""FastAPI application factory wiring the A2A protocol v1.0 routes."""

from __future__ import annotations

import os

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI

from .card import build_agent_card
from .executor import RoleFitExecutor
from .fit import load_profile, portfolio_summary, render_fit_report, score_role_fit

DEFAULT_BASE_URL = "http://127.0.0.1:8024"


def build_task_store():
    """In-memory by default.

    A single-process deployment is fine with memory. Serverless/multi-instance
    deployments must swap in a database-backed store so task state survives
    across invocations (see a2a.server.tasks.database_task_store).
    """
    return InMemoryTaskStore()


def create_app(base_url: str | None = None) -> FastAPI:
    """Build the ASGI app: agent card + JSON-RPC binding + REST binding."""
    base = (base_url or os.environ.get("A2A_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    profile = load_profile()
    card = build_agent_card(base)
    handler = DefaultRequestHandler(
        agent_executor=RoleFitExecutor(profile),
        task_store=build_task_store(),
        agent_card=card,
    )

    app = FastAPI(title="Role Fit Agent (A2A v1.0)", version=card.version)
    app.state.agent_card = card
    app.state.request_handler = handler

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "agent": card.name, "protocol": card.version,
                "base_url": base}

    @app.get("/fit")
    async def fit(jd: str = "") -> dict:
        """Convenience HTTP endpoint for humans; not part of the A2A protocol."""
        return score_role_fit(jd, profile)

    @app.get("/portfolio")
    async def portfolio() -> dict:
        return {"report": portfolio_summary(profile)}

    # Mount the standard A2A surface. add_a2a_routes_to_fastapi must be called
    # before the app starts serving so the card and RPC routes are registered.
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
        rest_routes=create_rest_routes(handler, path_prefix="/rest"),
    )
    return app


app = create_app()
