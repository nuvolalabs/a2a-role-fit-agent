# Calling the Role Fit Agent from a client

This is the concrete, verified guide for invoking this A2A v1.0 agent from any client.
The live deployment used throughout is:

```
https://a2a-role-fit-agent.vercel.app
```

Swap that for `http://127.0.0.1:8024` when running the server locally
(`PYTHONPATH=src python -m rolefit`).

A2A is a two-step handshake: **discover** the Agent Card, then **send a message**.

```
client agent  --GET  /.well-known/agent-card.json-->  discover
              --POST SendMessage (JSON-RPC)------->  task
              <---- Task(COMPLETED) + Artifact -----  scored fit report
```

---

## 1. The bundled client (easiest)

Stdlib-only, so the wire format is visible end to end.

```bash
cd a2a-role-fit-agent
python3 client.py --url https://a2a-role-fit-agent.vercel.app \
  "Must have Python, RAG and agentic orchestration."

# discovery only:
python3 client.py --url https://a2a-role-fit-agent.vercel.app --card-only
```

It fetches the card, picks the JSON-RPC interface, sends the message, and prints the
artifact text.

---

## 2. Raw JSON-RPC over curl

**Step 1 — discover** (pick the JSON-RPC url from `supportedInterfaces[0].url`):

```bash
curl -s https://a2a-role-fit-agent.vercel.app/.well-known/agent-card.json
```

**Step 2 — send** a message to that url:

```bash
curl -s https://a2a-role-fit-agent.vercel.app/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "c-1",
        "role": "ROLE_USER",
        "parts": [{"text": "Must have Python, RAG and agentic orchestration."}]
      }
    }
  }'
```

The response is a `Task`. The scored report is in
`result.task.artifacts[].parts[].text`.

**Step 3 (optional) — fetch the task by id in a SEPARATE request.** This is the real
proof that task state survives across serverless invocations:

```bash
curl -s https://a2a-role-fit-agent.vercel.app/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{"jsonrpc":"2.0","id":2,"method":"GetTask","params":{"id":"<task-id>"}}'
```

---

## 3. REST binding (HTTP+JSON)

Same operations with no JSON-RPC envelope:

```bash
POST https://a2a-role-fit-agent.vercel.app/rest/message:send
GET  https://a2a-role-fit-agent.vercel.app/rest/tasks/{id}
```

---

## Gotchas that cause most failed calls

- **Always send the header `A2A-Version: 1.0`.** Omit it and the server negotiates down
  to 0.3 and can reject the request with a 400.
- **Method names are PascalCase in v1.0:** `SendMessage`, `SendStreamingMessage`,
  `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`,
  `Create/Get/List/DeleteTaskPushNotificationConfig`, `GetExtendedAgentCard`. The old
  names (`message/send`, `tasks/get`) are gone.
- **JSON-RPC errors come back with HTTP 200.** Check the body's `error` field, not the
  HTTP status code.
- **Use the URL advertised in `supportedInterfaces`** — don't hardcode a path.
- `SendMessage` and `GetTask` use the same endpoint; only the `method` changes.

---

## Verified live example

Command:

```bash
python3 client.py --url https://a2a-role-fit-agent.vercel.app \
  "Must have Python, RAG, agentic orchestration, LangChain and Kubernetes."
```

Output:

```
Agent Card
  name       : Role Fit Agent
  version    : 1.0.0
  interface  : JSONRPC v1.0 -> https://a2a-role-fit-agent.vercel.app/
  interface  : HTTP+JSON v1.0 -> https://a2a-role-fit-agent.vercel.app/rest
  skill      : evaluate_role_fit - Evaluate Role Fit
  skill      : portfolio_summary - Portfolio Summary

-> SendMessage to https://a2a-role-fit-agent.vercel.app/
task 2cfd8cd3-e32d-4ba3-be10-9ba06204a218  state=TASK_STATE_COMPLETED

--- artifact ---
ROLE FIT: Arun Sreedhar -> Applied GenAI / LLM Engineer
score 36/100 [#######.............] verdict=weak

Matched capabilities (3):
  - Agentic orchestration (matched: agentic, orchestration)
      evidence: Built an agentic tool orchestrator with registry, memory and planning - 17 tests.
  - Python (matched: python)
      evidence: All five portfolio services are pure-Python with stdlib test suites.
  - RAG / retrieval (matched: rag)
      evidence: Built a RAG eval harness from scratch (chunking, retrieval, faithfulness metrics) - 14 tests.

Unclaimed requirements (2):
  - LangChain / LangGraph [MUST-HAVE]
  - Kubernetes [MUST-HAVE]
```

Note the honest negative result: the report does **not** claim LangChain or Kubernetes.
