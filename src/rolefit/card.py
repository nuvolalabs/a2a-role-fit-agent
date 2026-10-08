"""Agent Card for the Role Fit Agent (A2A protocol v1.0)."""

from __future__ import annotations

from a2a.types import a2a_pb2 as pb
from a2a.utils import constants as C

AGENT_NAME = "Role Fit Agent"
AGENT_DESCRIPTION = (
    "Evaluates how well a job description matches a specific engineering "
    "candidate's verified, shipped capabilities, and reports the gap honestly. "
    "Accepts a pasted job posting and returns a scored fit report with evidence "
    "drawn from real open-source projects."
)

SKILL_FIT = {
    "id": "evaluate_role_fit",
    "name": "Evaluate Role Fit",
    "description": (
        "Given the text of a job description, score how well it matches the "
        "candidate's demonstrated capabilities, list unclaimed requirements "
        "(flagging must-haves) and cite portfolio evidence for every match."
    ),
    "tags": ["recruiting", "job-description", "skills-matching", "evaluation"],
    "examples": [
        "Evaluate this job description: We are hiring an LLM Engineer with RAG "
        "and agentic experience, Python and vector databases. LangChain required.",
        "How well does this role fit? Must have Kubernetes and Terraform.",
    ],
}

SKILL_PORTFOLIO = {
    "id": "portfolio_summary",
    "name": "Portfolio Summary",
    "description": (
        "Return the candidate's shipped portfolio: each project, what it proves "
        "and its test count. Use when asked what has actually been built."
    ),
    "tags": ["portfolio", "projects", "evidence"],
    "examples": [
        "Summarise your portfolio",
        "What projects have you built?",
    ],
}

_TEXT = "text/plain"


def _add_skill(card: pb.AgentCard, spec: dict) -> None:
    skill = card.skills.add()
    skill.id = spec["id"]
    skill.name = spec["name"]
    skill.description = spec["description"]
    skill.tags.extend(spec["tags"])
    skill.examples.extend(spec["examples"])
    skill.input_modes.extend([_TEXT])
    skill.output_modes.extend([_TEXT])


def build_agent_card(base_url: str, version: str = "1.0.0") -> pb.AgentCard:
    """Build the A2A Agent Card advertised at /.well-known/agent-card.json.

    Declares two interfaces for the same agent: JSON-RPC 2.0 at the root and
    the HTTP+JSON (REST) binding under /rest.
    """
    base = base_url.rstrip("/")
    card = pb.AgentCard()
    card.name = AGENT_NAME
    card.description = AGENT_DESCRIPTION
    card.version = version
    card.documentation_url = f"{base}/docs"

    rpc = card.supported_interfaces.add()
    rpc.url = f"{base}/"
    rpc.protocol_binding = "JSONRPC"
    rpc.protocol_version = C.PROTOCOL_VERSION_CURRENT

    rest = card.supported_interfaces.add()
    rest.url = f"{base}/rest"
    rest.protocol_binding = "HTTP+JSON"
    rest.protocol_version = C.PROTOCOL_VERSION_CURRENT

    card.default_input_modes.extend([_TEXT, "application/json"])
    card.default_output_modes.extend([_TEXT])

    card.capabilities.streaming = True
    card.capabilities.push_notifications = True

    _add_skill(card, SKILL_FIT)
    _add_skill(card, SKILL_PORTFOLIO)
    return card
