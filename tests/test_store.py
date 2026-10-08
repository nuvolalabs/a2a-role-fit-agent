"""Tests for the Supabase PostgREST-backed TaskStore.

Hermetic: a fake PostgREST handler is injected through httpx.MockTransport, so
these run with no network and no credentials. The store's HTTP contract is
exercised for real (request building, upsert, filters, serialisation).
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path

import httpx
from google.protobuf.timestamp_pb2 import Timestamp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a2a.auth.user import User  # noqa: E402
from a2a.server.context import ServerCallContext  # noqa: E402
from a2a.types import a2a_pb2 as pb  # noqa: E402

from rolefit.store import SupabaseTaskStore  # noqa: E402


class NamedUser(User):
    def __init__(self, name):
        self._name = name

    @property
    def is_authenticated(self):
        return True

    @property
    def user_name(self):
        return self._name


def ctx(name=""):
    """A call context; an empty name mirrors an unauthenticated A2A caller."""
    return ServerCallContext(user=NamedUser(name) if name else _Anon())


class _Anon(User):
    @property
    def is_authenticated(self):
        return False

    @property
    def user_name(self):
        return ""


class FakePostgrest:
    """Minimal stand-in for PostgREST backed by a dict."""

    def __init__(self):
        self.rows = {}
        self.calls = []

    @staticmethod
    def _eq(params, key):
        raw = params.get(key)
        return raw[3:] if raw and raw.startswith("eq.") else raw

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append((request.method, request.url.path, params))

        if request.method == "POST":
            row = json.loads(request.content)
            self.rows[(row["id"], row["owner"])] = row
            return httpx.Response(201, json=[row])

        if request.method == "GET":
            owner = self._eq(params, "owner")
            rows = [r for r in self.rows.values() if r["owner"] == owner]
            tid = self._eq(params, "id")
            if tid:
                rows = [r for r in rows if r["id"] == tid]
            cid = self._eq(params, "context_id")
            if cid:
                rows = [r for r in rows if r.get("context_id") == cid]
            return httpx.Response(200, json=rows[: int(params.get("limit", 100))])

        if request.method == "DELETE":
            owner = self._eq(params, "owner")
            tid = self._eq(params, "id")
            for key in [k for k in self.rows if k[1] == owner and k[0] == tid]:
                del self.rows[key]
            return httpx.Response(204)

        return httpx.Response(405)


def make_task(task_id, context_id="ctx-1", ts_ns=1_700_000_000_000_000_000,
              text="report body"):
    task = pb.Task(id=task_id, context_id=context_id,
                   status=pb.TaskStatus(state=pb.TASK_STATE_COMPLETED))
    stamp = Timestamp()
    stamp.FromNanoseconds(ts_ns)
    task.status.timestamp.CopyFrom(stamp)
    artifact = task.artifacts.add()
    artifact.artifact_id = "a-1"
    artifact.name = "report"
    artifact.parts.add().text = text
    return task


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakePostgrest()
        self.store = SupabaseTaskStore(
            "https://example.supabase.co", "service-key",
            transport=httpx.MockTransport(self.fake.handler))

    def run_async(self, coro):
        return asyncio.run(coro)


class TestRoundTrip(StoreTestCase):
    def test_save_then_get_preserves_the_task(self):
        task = make_task("t-1")
        self.run_async(self.store.save(task, ctx()))
        got = self.run_async(self.store.get("t-1", ctx()))

        self.assertIsNotNone(got)
        self.assertEqual(got.id, "t-1")
        self.assertEqual(got.context_id, "ctx-1")
        self.assertEqual(got.status.state, pb.TASK_STATE_COMPLETED)
        self.assertEqual(got.status.timestamp.ToNanoseconds(),
                         task.status.timestamp.ToNanoseconds())
        self.assertEqual(got.artifacts[0].name, "report")
        self.assertEqual(got.artifacts[0].parts[0].text, "report body")

    def test_get_missing_task_returns_none(self):
        self.assertIsNone(self.run_async(self.store.get("nope", ctx())))

    def test_save_is_an_upsert_not_a_duplicate(self):
        self.run_async(self.store.save(make_task("t-1", text="first"), ctx()))
        self.run_async(self.store.save(make_task("t-1", text="second"), ctx()))
        self.assertEqual(len(self.fake.rows), 1)
        got = self.run_async(self.store.get("t-1", ctx()))
        self.assertEqual(got.artifacts[0].parts[0].text, "second")

    def test_save_sends_merge_preference_and_conflict_key(self):
        self.run_async(self.store.save(make_task("t-1"), ctx()))
        method, path, params = self.fake.calls[-1]
        self.assertEqual(method, "POST")
        self.assertTrue(path.endswith("/a2a_tasks"))
        self.assertEqual(params["on_conflict"], "id,owner")

    def test_timestamp_is_stored_as_rfc3339(self):
        self.run_async(self.store.save(make_task("t-1"), ctx()))
        row = next(iter(self.fake.rows.values()))
        self.assertTrue(row["last_updated"].endswith("Z"), row["last_updated"])
        self.assertEqual(row["protocol_version"], "1.0")


class TestOwnerScoping(StoreTestCase):
    def test_tasks_are_scoped_per_owner(self):
        self.run_async(self.store.save(make_task("t-1"), ctx("alice")))
        self.assertIsNotNone(self.run_async(self.store.get("t-1", ctx("alice"))))
        self.assertIsNone(self.run_async(self.store.get("t-1", ctx("bob"))))

    def test_anonymous_callers_share_one_scope(self):
        # Our server has no auth, so every caller resolves to the "" owner and
        # can therefore GetTask for tasks it created in an earlier invocation.
        self.run_async(self.store.save(make_task("t-1"), ctx()))
        self.assertIsNotNone(self.run_async(self.store.get("t-1", ctx())))


class TestDelete(StoreTestCase):
    def test_delete_removes_only_that_task(self):
        self.run_async(self.store.save(make_task("t-1"), ctx()))
        self.run_async(self.store.save(make_task("t-2"), ctx()))
        self.run_async(self.store.delete("t-1", ctx()))
        self.assertIsNone(self.run_async(self.store.get("t-1", ctx())))
        self.assertIsNotNone(self.run_async(self.store.get("t-2", ctx())))

    def test_delete_missing_is_a_noop(self):
        self.run_async(self.store.delete("absent", ctx()))
        self.assertEqual(len(self.fake.rows), 0)


class TestList(StoreTestCase):
    def _seed(self):
        for i in range(3):
            self.run_async(self.store.save(
                make_task(f"t-{i}", ts_ns=1_700_000_000_000_000_000 + i * 1_000_000_000),
                ctx()))

    def test_lists_newest_first(self):
        self._seed()
        resp = self.run_async(self.store.list(pb.ListTasksRequest(), ctx()))
        self.assertEqual([t.id for t in resp.tasks], ["t-2", "t-1", "t-0"])
        self.assertEqual(resp.total_size, 3)

    def test_pagination_returns_a_usable_cursor(self):
        self._seed()
        first = self.run_async(
            self.store.list(pb.ListTasksRequest(page_size=2), ctx()))
        self.assertEqual([t.id for t in first.tasks], ["t-2", "t-1"])
        self.assertTrue(first.next_page_token)
        self.assertEqual(first.total_size, 3)

        second = self.run_async(self.store.list(
            pb.ListTasksRequest(page_size=2, page_token=first.next_page_token), ctx()))
        self.assertEqual([t.id for t in second.tasks], ["t-0"])
        self.assertFalse(second.next_page_token)

    def test_page_size_defaults_when_unset(self):
        self._seed()
        resp = self.run_async(self.store.list(pb.ListTasksRequest(), ctx()))
        self.assertEqual(resp.page_size, 50)

    def test_filters_by_context_id(self):
        self.run_async(self.store.save(make_task("a", context_id="ctx-a"), ctx()))
        self.run_async(self.store.save(make_task("b", context_id="ctx-b"), ctx()))
        resp = self.run_async(
            self.store.list(pb.ListTasksRequest(context_id="ctx-a"), ctx()))
        self.assertEqual([t.id for t in resp.tasks], ["a"])

    def test_filters_by_status(self):
        self.run_async(self.store.save(make_task("done", ts_ns=1), ctx()))
        working = make_task("working", ts_ns=2)
        working.status.state = pb.TASK_STATE_WORKING
        self.run_async(self.store.save(working, ctx()))
        resp = self.run_async(self.store.list(
            pb.ListTasksRequest(status=pb.TASK_STATE_WORKING), ctx()))
        self.assertEqual([t.id for t in resp.tasks], ["working"])

    def test_list_is_scoped_to_the_owner(self):
        self.run_async(self.store.save(make_task("t-1"), ctx("alice")))
        resp = self.run_async(self.store.list(pb.ListTasksRequest(), ctx("bob")))
        self.assertEqual(resp.tasks, [])
        self.assertEqual(resp.total_size, 0)


class TestStoreSelection(unittest.TestCase):
    """build_task_store picks Supabase when configured, memory otherwise."""

    def test_supabase_store_is_selected_when_env_is_present(self):
        import os
        from unittest import mock

        from rolefit.app import build_task_store
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://x.supabase.co",
                                          "SUPABASE_SERVICE_KEY": "k"}):
            self.assertIsInstance(build_task_store(), SupabaseTaskStore)

    def test_memory_store_is_the_fallback(self):
        import os
        from unittest import mock

        from a2a.server.tasks import InMemoryTaskStore
        from rolefit.app import build_task_store
        bare = {k: v for k, v in os.environ.items()
                if k not in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY",
                             "SUPABASE_SERVICE_ROLE_KEY")}
        with mock.patch.dict(os.environ, bare, clear=True):
            self.assertIsInstance(build_task_store(), InMemoryTaskStore)

    def test_table_name_is_configurable(self):
        import os
        from unittest import mock

        from rolefit.app import build_task_store
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://x.supabase.co",
                                          "SUPABASE_SERVICE_KEY": "k",
                                          "A2A_TASKS_TABLE": "custom_tasks"}):
            self.assertEqual(build_task_store().table, "custom_tasks")


if __name__ == "__main__":
    unittest.main(verbosity=2)
