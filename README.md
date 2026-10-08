# A2A Role Fit Agent

An [Agent2Agent (A2A) protocol](https://a2a-protocol.org/) **v1.0** server that exposes a
real capability to other agents: evaluating how well a job description matches a
specific engineer's *verified, shipped* skills — and reporting the gaps honestly.

It publishes an Agent Card, speaks JSON-RPC 2.0 and the HTTP+JSON (REST) binding, and
runs the full A2A task lifecycle (`submitted → working → completed`) with artifacts.

Built with the official [`a2a-sdk`](https://github.com/a2aproject/a2a-python) (1.2.x,
protocol 1.0) on FastAPI. 25 tests, no network or LLM required to run them.

```
client agent  --GET /.well-known/agent-card.json-->  discover
              --POST SendMessage (JSON-RPC)------->  task
              <---- Task(COMPLETED) + Artifact -----  scored fit report
```

## Why A2A next to MCP

They solve different halves of the same problem, and this repo is deliberately the
other half of [`mcp-tool-server`](https://github.com/nuvolalabs/mcp-tool-server):

| | MCP | A2A |
|---|---|---|
| Connects | agent **→ tools / data** | agent **→ agent** |
| Unit | tool, resource, prompt | task, artifact, message |
| Discovery | server capabilities | **Agent Card** at a well-known URL |
| Interaction | request/response | long-running **tasks**, streaming, push notifications |

MCP gives an agent hands. A2A gives agents colleagues.

## What it exposes

| Skill | Input | Output |
|---|---|---|
| `evaluate_role_fit` | a pasted job description | scored fit report: matched capabilities with evidence, unclaimed requirements (must-haves flagged), portfolio proof points |
| `portfolio_summary` | a question about projects | the shipped portfolio with per-project test counts |

The scoring is **deterministic and testable** — no LLM call, no network. Every
number is reproducible from the job text plus `src/rolefit/profile.json`.

## Quickstart

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# run the agent (defaults to http://127.0.0.1:8024)
PYTHONPATH=src python -m rolefit

# in another shell: discover + call it
python client.py --url http://127.0.0.1:8024 "Must have Python, RAG and agentic orchestration."
python client.py --url http://127.0.0.1:8024 --card-only
```

## Protocol surface

Verified live against a running server (see transcript below).

| A2A operation | JSON-RPC method | REST endpoint | Status |
|---|---|---|---|
| Send message | `SendMessage` | `POST /message:send` | implemented |
| Send streaming | `SendStreamingMessage` | `POST /message:stream` | advertised (`capabilities.streaming`) |
| Get task | `GetTask` | `GET /tasks/{id}` | implemented |
| List tasks | `ListTasks` | `GET /tasks` | implemented |
| Cancel task | `CancelTask` | `POST /tasks/{id}:cancel` | implemented |
| Subscribe | `SubscribeToTask` | `POST /tasks/{id}:subscribe` | implemented |
| Push notification configs | `Create/Get/List/DeleteTaskPushNotificationConfig` | `/tasks/{id}/pushNotificationConfigs` | advertised (`capabilities.pushNotifications`) |
| Agent Card | — | `GET /.well-known/agent-card.json` | implemented |

Method names are readonly PascalCase in v1.0 — the pre-1.0 names (`message/send`,
`tasks/get`) are **not** used here.

Requests carry `A2A-Version: 1.0`. The binding also exposes a v0.3 compatibility mode
that this server leaves off.

## Live transcript

Agent Card (abridged):

```json
{
  "name": "Role Fit Agent",
  "version": "1.0.0",
  "supportedInterfaces": [
    { "url": "http://127.0.0.1:8024/",     "protocolBinding": "JSONRPC",   "protocolVersion": "1.0" },
    { "url": "http://127.0.0.1:8024/rest", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0" }
  ],
  "capabilities": { "streaming": true, "pushNotifications": true },
  "skills": [
    { "id": "evaluate_role_fit", "name": "Evaluate Role Fit" },
    { "id": "portfolio_summary", "name": "Portfolio Summary" }
  ]
}
```

`SendMessage` → completed task with an artifact:

```
task  621fa29c-c713-41c7-87b0-db1135e6a107
state TASK_STATE_COMPLETED

--- artifact ---
ROLE FIT: Arun Sreedhar -> Applied GenAI / LLM Engineer
score 45/100 [#########...........] verdict=partial

Matched capabilities (5):
  - Agentic orchestration (matched: agentic, orchestration)
      evidence: Built an agentic tool orchestrator with registry, memory and planning - 17 tests.
  - Python (matched: python)
      evidence: All five portfolio services are pure-Python with stdlib test suites.
  - RAG / retrieval (matched: rag)
      evidence: Built a RAG eval harness from scratch (chunking, retrieval, faithfulness metrics) - 14 tests.
  - FastAPI (matched: fastapi)
      evidence: FastAPI tool-server powering the voicebite VoIP product.
  - MCP (Model Context Protocol) (matched: mcp)
      evidence: Built an MCP tool server speaking JSON-RPC 2.0 over stdio - 11 tests.

Unclaimed requirements (2):
  - LangChain / LangGraph [MUST-HAVE]
  - Kubernetes [MUST-HAVE]
```

Note the honest negative result: the report **does not** claim LangChain or Kubernetes.
`GetTask` for the same task returns `TASK_STATE_COMPLETED` with the same artifact.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

25 tests in two suites:

- `tests/test_fit.py` — scoring determinism, must-have gap detection, evidence
  attachment, and **profile-integrity guards** (a capability may never be listed as
  both a strength and a gap).
- `tests/test_server.py` — real HTTP against the ASGI app: card contents at the
  well-known path, both bindings, `SendMessage`/`GetTask` round-trip, JSON-RPC error
  codes, artifact payload.

## Deploy

### Vercel (default)

`api/index.py` exposes the ASGI `app`; `vercel.json` routes everything (including
`/.well-known/agent-card.json`) to it.

```bash
vercel --prod
vercel env add A2A_BASE_URL production   # e.g. https://<project>.vercel.app
```

Set `A2A_BASE_URL` so the Agent Card advertises the real public URLs, not localhost.

**Serverless caveat:** the default task store is in-memory, so task state does not
survive across invocations. For production on serverless, swap in the SDK's
database-backed store (`a2a.server.tasks.database_task_store`) — see
`build_task_store()` in `src/rolefit/app.py`. Streaming responses are also capped by
the function's max duration, which is why the long-lived/streaming path is better on a
container.

### Container (Railway / Cloud Run / Fly)

```bash
docker build -t a2a-role-fit-agent .
docker run -p 8080:8080 -e A2A_BASE_URL=http://localhost:8080 a2a-role-fit-agent
```

The container runs a single long-lived process, so in-memory task state, SSE streaming
and push notifications all work as the spec intends.

## Layout

```
src/rolefit/
  card.py       # Agent Card (v1.0): interfaces, capabilities, skills
  fit.py        # pure deterministic scoring + report rendering
  executor.py   # AgentExecutor: task lifecycle, status updates, artifact
  app.py        # FastAPI app factory, binds card + JSON-RPC + REST routes
  profile.json  # the candidate profile the agent reasons over
  __main__.py   # `python -m rolefit`
client.py       # stdlib A2A client: card handshake + SendMessage
api/index.py    # Vercel entrypoint
tests/          # 25 tests
```

## Design notes

- **Honesty over sales.** The agent reports unclaimed requirements rather than
  inflating a score. That is a deliberate product choice: a fit agent that always says
  "perfect match" is useless to the agent that delegated to it.
- **Deterministic core.** Scoring is pure functions over text + profile, so it is unit
  testable and free. An LLM layer (rewriting the report in prose, or extracting
  requirements from messy postings) is a natural next step and would sit *behind* this
  core, not replace it.
- **The protocol is the product.** The SDK handles the wire format; this repo's job is
  to show a correct card, a correct task lifecycle, and both bindings.
