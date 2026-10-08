"""Protocol tests: real HTTP calls against the ASGI app (no network, no mocks)."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from a2a.server.tasks import InMemoryTaskStore  # noqa: E402
from rolefit.app import create_app  # noqa: E402

CARD_URL = "/.well-known/agent-card.json"


def new_app():
    """Hermetic app: explicit in-memory store so tests never touch Supabase."""
    return create_app("https://example.test", task_store=InMemoryTaskStore())


JD = "Must have Python, RAG and agentic orchestration. Nice to have FastAPI and MCP."


class TestAgentCard(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(new_app())

    def test_card_is_served_at_well_known_path(self):
        r = self.client.get(CARD_URL)
        self.assertEqual(r.status_code, 200, r.text)
        self.card = r.json()
        self.assertEqual(self.card["name"], "Role Fit Agent")
        self.assertEqual(self.card["version"], "1.0.0")

    def test_card_declares_both_interfaces(self):
        card = self.client.get(CARD_URL).json()
        bindings = {i["protocolBinding"] for i in card["supportedInterfaces"]}
        self.assertEqual(bindings, {"JSONRPC", "HTTP+JSON"})
        for i in card["supportedInterfaces"]:
            self.assertEqual(i["protocolVersion"], "1.0")
            self.assertTrue(i["url"].startswith("https://example.test"))

    def test_card_advertises_skills_and_capabilities(self):
        card = self.client.get(CARD_URL).json()
        self.assertEqual({s["id"] for s in card["skills"]},
                         {"evaluate_role_fit", "portfolio_summary"})
        for s in card["skills"]:
            self.assertTrue(s["description"])
            self.assertTrue(s["examples"])
        self.assertTrue(card["capabilities"]["streaming"])
        self.assertTrue(card["capabilities"]["pushNotifications"])

    def test_healthz(self):
        body = self.client.get("/healthz").json()
        self.assertEqual(body["status"], "ok")


class TestJsonRpcBinding(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(new_app())

    def _rpc(self, method, params=None, rpc_id=1):
        payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
        if params is not None:
            payload["params"] = params
        return self.client.post("/", json=payload,
                                headers={"Content-Type": "application/json",
                                         "A2A-Version": "1.0"})

    def test_send_message_returns_a_task(self):
        r = self._rpc("SendMessage", {"message": {
            "messageId": "m-1", "role": "ROLE_USER",
            "parts": [{"text": JD}]}})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotIn("error", body, body)
        self.assertIn("result", body)
        task = body["result"].get("task") or body["result"]
        self.assertTrue(task["id"])
        self.assertTrue(task["contextId"])

    def test_task_is_completed_and_carries_the_report(self):
        r = self._rpc("SendMessage", {"message": {
            "messageId": "m-2", "role": "ROLE_USER", "parts": [{"text": JD}]}})
        result = r.json()["result"]
        task = result.get("task") or result
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED",
                         json.dumps(task["status"])[:400])
        self.assertTrue(task["artifacts"], "no artifact produced")
        text = "".join(p.get("text", "") for p in task["artifacts"][0]["parts"])
        self.assertIn("/100", text)

    def test_get_task_round_trips(self):
        r = self._rpc("SendMessage", {"message": {
            "messageId": "m-3", "role": "ROLE_USER", "parts": [{"text": JD}]}})
        task_id = (r.json()["result"].get("task") or r.json()["result"])["id"]
        r2 = self._rpc("GetTask", {"id": task_id}, rpc_id=2)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertNotIn("error", r2.json(), r2.text)

    def test_unknown_method_is_a_jsonrpc_error(self):
        r = self._rpc("NoSuchMethod")
        self.assertIn("error", r.json())

    def test_malformed_body_returns_jsonrpc_parse_error(self):
        # JSON-RPC transports errors in the body with HTTP 200 (spec behaviour).
        r = self.client.post("/", content=b"not json",
                             headers={"Content-Type": "application/json",
                                      "A2A-Version": "1.0"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["error"]["code"], -32700)


class TestRestBinding(unittest.TestCase):
    def test_message_send_endpoint_completes_a_task(self):
        client = TestClient(new_app())
        r = client.post("/rest/message:send",
                        json={"message": {"messageId": "r-1", "role": "ROLE_USER",
                                          "parts": [{"text": JD}]}},
                        headers={"Content-Type": "application/json",
                                 "A2A-Version": "1.0"})
        self.assertEqual(r.status_code, 200, r.text)
        task = r.json()["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        text = "".join(p.get("text", "") for p in task["artifacts"][0]["parts"])
        self.assertIn("/100", text)


class TestConvenienceEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(new_app())

    def test_fit_endpoint(self):
        body = self.client.get("/fit", params={"jd": JD}).json()
        self.assertGreater(body["score"], 0)
        self.assertTrue(body["matched"])

    def test_portfolio_endpoint(self):
        body = self.client.get("/portfolio").json()
        self.assertIn("rag-eval-harness", body["report"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
