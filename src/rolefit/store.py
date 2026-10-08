"""TaskStore backed by Supabase PostgREST.

Why not the SDK's `DatabaseTaskStore`? That one needs SQLAlchemy plus a database
driver and a Postgres connection string (and, from serverless, the pooler with
prepared statements disabled). Supabase already gives us a service key and a
PostgREST endpoint over HTTPS, so a small HTTP-backed store is both simpler and a
better fit for short-lived serverless invocations.

Semantics mirror the SDK's in-memory store exactly: tasks are scoped per owner,
listing supports the same filters, ordering and cursor pagination, and the same
`decode/encode_list_tasks_cursor` helpers are reused.
"""

from __future__ import annotations

from typing import Any

import httpx
from google.protobuf.json_format import MessageToDict, ParseDict

from a2a.server.context import ServerCallContext
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks.task_store import TaskStore
from a2a.types import a2a_pb2
from a2a.types.a2a_pb2 import Task
from a2a.utils.constants import DEFAULT_LIST_TASKS_PAGE_SIZE
from a2a.utils.errors import InvalidParamsError
from a2a.utils.task import (
    ListTasksCursor,
    decode_list_tasks_cursor,
    decode_page_token,
    encode_list_tasks_cursor,
)

DEFAULT_TABLE = "a2a_tasks"
# Safety bound on a single list scan; the endpoint is paginated, not unbounded.
MAX_ROWS = 1000
PROTOCOL_VERSION = "1.0"


def _sort_key(task: Task) -> tuple[bool, int, str]:
    """ListTasks sort key: `(has timestamp, timestamp, id)`, sorted descending."""
    has_timestamp = task.HasField("status") and task.status.HasField("timestamp")
    return (
        has_timestamp,
        task.status.timestamp.ToNanoseconds() if has_timestamp else 0,
        task.id,
    )


def _cursor_for(task: Task) -> ListTasksCursor:
    has_timestamp, timestamp_ns, task_id = _sort_key(task)
    return ListTasksCursor(
        timestamp_ns=timestamp_ns if has_timestamp else None, task_id=task_id
    )


class SupabaseTaskStore(TaskStore):
    """Stores A2A tasks in a Supabase table reached over PostgREST."""

    def __init__(self, url: str, service_key: str, table: str = DEFAULT_TABLE,
                 timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None,
                 max_rows: int = MAX_ROWS) -> None:
        self.base_url = url.rstrip("/") + "/rest/v1"
        self.table = table
        self.timeout = timeout
        self.max_rows = max_rows
        self._transport = transport
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ plumbing

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, headers=self._headers,
                                 timeout=self.timeout, transport=self._transport)

    @staticmethod
    def _owner(context: ServerCallContext) -> str:
        return resolve_user_scope(context)

    @staticmethod
    def _to_row(task: Task, owner: str) -> dict[str, Any]:
        has_ts = task.HasField("status") and task.status.HasField("timestamp")
        return {
            "id": task.id,
            "owner": owner,
            "context_id": task.context_id,
            "kind": "task",
            # RFC3339 with Z, which PostgREST accepts for timestamptz.
            "last_updated": task.status.timestamp.ToJsonString() if has_ts else None,
            "status": MessageToDict(task.status) if task.HasField("status") else None,
            "artifacts": [MessageToDict(a) for a in task.artifacts],
            "history": [MessageToDict(m) for m in task.history],
            "task_metadata": (
                MessageToDict(task.metadata) if task.metadata.fields else None
            ),
            "protocol_version": PROTOCOL_VERSION,
        }

    @staticmethod
    def _from_row(row: dict[str, Any]) -> Task:
        task = Task(id=row["id"], context_id=row.get("context_id") or "")
        if row.get("status"):
            ParseDict(row["status"], task.status)
        for art in row.get("artifacts") or []:
            ParseDict(art, task.artifacts.add())
        for msg in row.get("history") or []:
            ParseDict(msg, task.history.add())
        if row.get("task_metadata"):
            task.metadata.update(row["task_metadata"])
        return task

    # ------------------------------------------------------------------- TaskStore

    async def save(self, task: Task, context: ServerCallContext) -> None:
        """Upsert a task, keyed on (id, owner)."""
        row = self._to_row(task, self._owner(context))
        async with self._client() as client:
            resp = await client.post(
                f"/{self.table}",
                json=row,
                params={"on_conflict": "id,owner"},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            resp.raise_for_status()

    async def get(self, task_id: str, context: ServerCallContext) -> Task | None:
        """Fetch one task for the calling owner."""
        async with self._client() as client:
            resp = await client.get(
                f"/{self.table}",
                params={"select": "*", "limit": 1,
                        "id": f"eq.{task_id}", "owner": f"eq.{self._owner(context)}"},
            )
            resp.raise_for_status()
            rows = resp.json()
        return self._from_row(rows[0]) if rows else None

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        """Delete a task for the calling owner (no-op when absent)."""
        async with self._client() as client:
            resp = await client.delete(
                f"/{self.table}",
                params={"id": f"eq.{task_id}", "owner": f"eq.{self._owner(context)}"},
            )
            resp.raise_for_status()

    async def list(self, params: a2a_pb2.ListTasksRequest,
                   context: ServerCallContext) -> a2a_pb2.ListTasksResponse:
        """List tasks with the same filters, ordering and cursors as the SDK."""
        query: dict[str, Any] = {
            "select": "*",
            "owner": f"eq.{self._owner(context)}",
            "limit": self.max_rows,
            "order": "last_updated.desc.nullslast,id.desc",
        }
        if params.context_id:
            query["context_id"] = f"eq.{params.context_id}"

        async with self._client() as client:
            resp = await client.get(f"/{self.table}", params=query)
            resp.raise_for_status()
            rows = resp.json()

        tasks = [self._from_row(row) for row in rows]

        # Same post-filters as the SDK's in-memory store.
        if params.status:
            tasks = [t for t in tasks if t.status.state == params.status]
        if params.HasField("status_timestamp_after"):
            after_ns = params.status_timestamp_after.ToNanoseconds()
            tasks = [
                t for t in tasks
                if t.HasField("status") and t.status.HasField("timestamp")
                and t.status.timestamp.ToNanoseconds() >= after_ns
            ]

        tasks.sort(key=_sort_key, reverse=True)

        total_size = len(tasks)
        start_idx = 0
        if params.page_token:
            cursor = decode_list_tasks_cursor(params.page_token)
            if cursor is None:
                start_idx = self._legacy_start_index(tasks, params.page_token)
            else:
                after = cursor.sort_key()
                start_idx = next(
                    (i for i, t in enumerate(tasks) if _sort_key(t) < after),
                    total_size,
                )
        page_size = params.page_size or DEFAULT_LIST_TASKS_PAGE_SIZE
        end_idx = start_idx + page_size
        next_page_token = (
            encode_list_tasks_cursor(_cursor_for(tasks[end_idx - 1]))
            if end_idx < total_size else None
        )

        return a2a_pb2.ListTasksResponse(
            tasks=tasks[start_idx:end_idx],
            next_page_token=next_page_token,
            total_size=total_size,
            page_size=page_size,
        )

    @staticmethod
    def _legacy_start_index(tasks: list[Task], page_token: str) -> int:
        start_task_id = decode_page_token(page_token)
        for i, task in enumerate(tasks):
            if task.id == start_task_id:
                return i
        raise InvalidParamsError(f"Invalid page token: {page_token}")
