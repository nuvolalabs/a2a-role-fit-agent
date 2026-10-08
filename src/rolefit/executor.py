"""A2A AgentExecutor: turns an incoming message into a streamed task result."""

from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import a2a_pb2 as pb

from .fit import load_profile, portfolio_summary, render_fit_report, score_role_fit

PORTFOLIO_KEYWORDS = ("portfolio", "projects", "what have you built", "github",
                      "repositories", "repos")


def choose_skill(text: str) -> str:
    """Pick the skill for an incoming request. Deterministic, no LLM needed."""
    lowered = (text or "").lower()
    if any(k in lowered for k in PORTFOLIO_KEYWORDS):
        return "portfolio_summary"
    return "evaluate_role_fit"


class RoleFitExecutor(AgentExecutor):
    """Executes the Role Fit Agent's skills and publishes A2A task updates."""

    def __init__(self, profile: dict | None = None) -> None:
        self.profile = profile or load_profile()

    def _message(self, text: str) -> pb.Message:
        return pb.Message(role=pb.ROLE_AGENT, parts=[pb.Part(text=text)])

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        skill = choose_skill(text)
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        # A2A requires the agent to publish the initial Task object *before* any
        # TaskStatusUpdateEvent, so the handler has state to attach them to.
        await event_queue.enqueue_event(pb.Task(
            id=context.task_id,
            context_id=context.context_id,
            status=pb.TaskStatus(state=pb.TASK_STATE_SUBMITTED),
        ))
        await updater.start_work(
            message=self._message(f"Running skill '{skill}' over the submitted text."))

        try:
            if skill == "portfolio_summary":
                report = portfolio_summary(self.profile)
            else:
                result = score_role_fit(text, self.profile)
                report = render_fit_report(result)
            await updater.add_artifact([pb.Part(text=report)], name=f"{skill}-report")
            await updater.complete(
                message=self._message(f"Skill '{skill}' completed."))
        except Exception as exc:  # surface failures as a failed task, not a 500
            await updater.failed(
                message=self._message(f"Skill '{skill}' failed: {exc}"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(message=self._message("Task cancelled by request."))
