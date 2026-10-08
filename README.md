# A2A Role Fit Agent

An [Agent2Agent (A2A) protocol](https://a2a-protocol.org/) **v1.0** server that exposes a
real capability to other agents: evaluating how well a job description matches a
specific engineer's *verified, shipped* skills — and reporting the gaps honestly.

It publishes an Agent Card, speaks JSON-RPC 2.0 and the HTTP+JSON (REST) binding, runs
the full A2A task lifecycle (`submitted → working → completed`) with artifacts, and
persists tasks in Postgres so state survives across serverless invocations.

Built with the official [`a2a-sdk`](https://github.com/a2aproject/a2a-python) (1.2.x,
protocol 1.0) on FastAPI. 43 tests, no network or LLM required to run them.

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

Calling the agent from your own client (curl, JSON-RPC, REST, gotchas):
see [`docs/calling-from-a-client.md`](docs/calling-from-a-client.md).

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

Method names are PascalCase in v1.0 — the pre-1.0 names (`message/send`, `tasks/get`)
are **not** used here.

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

## Task persistence

The default store is in-memory, which is fine for one long-lived process but **wrong
for serverless**: a task created by one invocation is gone by the next, so a follow-up
`GetTask` returns not-found and the agent looks broken.

Set `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` and the app automatically uses
`SupabaseTaskStore` — a `TaskStore` backed by Supabase PostgREST over HTTPS. That
avoids the SQLAlchemy/driver route (and the serverless pooler + prepared-statement
pitfalls that come with asyncpg) while giving real cross-invocation persistence.

```bash
# apply the schema (once), via the Supabase Management API
curl -s -X POST "https://api.supabase.com/v1/projects/$REF/database/query" \
  -H "Authorization: Bearer $SUPABASE_PAT" -H "Content-Type: application/json" \
  -d "{\"query\": $(python3 -c 'import json;print(json.dumps(open("supabase/schema.sql").read()))')}"
```

Verified against live Supabase: `save` → `get` through a **fresh client instance** →
`list` → `delete` → `get` returns nothing:

```
save: ok
get via a FRESH client instance: FOUND
  id        : roundtrip-proof-0001
  context_id: ctx-proof
  state     : 3
  artifact  : persisted through Supabase PostgREST
  timestamp : 2026-10-08T02:32:10.546361Z
list: total_size = 1 | contains proof: True
delete then get: MISSING (correct)
ROUND-TRIP: PASS
```

Storage semantics mirror the SDK's in-memory store: tasks are scoped per owner
(`context.user.user_name`, empty for unauthenticated callers), `ListTasks` supports the
same `context_id` / `status` / `status_timestamp_after` filters, the same
`(has_timestamp, timestamp, id)` descending order, and the same cursor pagination
helpers. RLS is enabled with no `anon` policies, so only the service key can touch
task state.

**Operational note (free tier):** a paused Supabase project (`status: INACTIVE`)
restores from the snapshot taken at pause time, and the restore runs *after* the API
returns. Applying this schema during that window appears to work — the query returns
`201` and the table answers for a few minutes — and then the finishing restore wipes
it. The symptom is PostgREST answering
`PGRST205 Could not find the table 'public.a2a_tasks' in the schema cache`, which
looks like a cache problem. Check with
`select to_regclass('public.a2a_tasks');` (SQL, via the Management API): `null` means
re-apply the schema. Wait for `ACTIVE_HEALTHY` first.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

43 tests in three suites:

- `tests/test_fit.py` — scoring determinism, must-have gap detection, evidence
  attachment, and **profile-integrity guards** (a capability may never be listed as
  both a strength and a gap).
- `tests/test_server.py` — real HTTP against the ASGI app: card contents at the
  well-known path, both bindings, `SendMessage`/`GetTask` round-trip, JSON-RPC error
  codes, artifact payload. Injects an explicit in-memory store so tests never touch
  Supabase.
- `tests/test_store.py` — the PostgREST store against a fake PostgREST over
  `httpx.MockTransport`: upsert rather than duplicate, owner scoping, protobuf
  round-trip fidelity, RFC3339 timestamps, pagination cursors, filters, and store
  selection from the environment.

## Deploy

### Vercel (default)

`api/index.py` exposes the ASGI `app`; `vercel.json` routes everything (including
`/.well-known/agent-card.json`) to it.

```bash
vercel --prod
vercel env add A2A_BASE_URL production            # https://<project>.vercel.app
vercel env add SUPABASE_URL production            # https://<ref>.supabase.co
vercel env add SUPABASE_SERVICE_KEY production    # service key, server-side only
```

- `A2A_BASE_URL` must be the public URL so the Agent Card advertises real endpoints
  rather than localhost.
- `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` are what make `GetTask` work across
  invocations. Without them the app logs a warning and falls back to memory.
- Streaming (`SendStreamingMessage`) is capped by the function's max duration. The
  card still advertises `capabilities.streaming` because the route exists; a container
  is the better home for long-lived SSE.

### Container (Railway / Cloud Run / Fly)

```bash
docker build -t a2a-role-fit-agent .
docker run -p 8080:8080 -e A2A_BASE_URL=http://localhost:8080 a2a-role-fit-agent
```

A single long-lived process, so in-memory task state, SSE streaming and push
notifications all behave exactly as the spec intends.

## Layout

```
src/rolefit/
  card.py        # Agent Card (v1.0): interfaces, capabilities, skills
  fit.py         # pure deterministic scoring + report rendering
  executor.py    # AgentExecutor: task lifecycle, status updates, artifact
  store.py       # SupabaseTaskStore: PostgREST-backed task persistence
  app.py         # FastAPI app factory, binds card + JSON-RPC + REST routes
  profile.json   # the candidate profile the agent reasons over
  __main__.py    # `python -m rolefit`
client.py        # stdlib A2A client: card handshake + SendMessage
api/index.py     # Vercel entrypoint
supabase/schema.sql   # a2a_tasks table (RLS on, no anon policies)
tests/           # 43 tests
```

## Design notes

- **Honesty over sales.** The agent reports unclaimed requirements rather than
  inflating a score. That is a deliberate product choice: a fit agent that always says
  "perfect match" is useless to the agent that delegated to it.
- **Deterministic core.** Scoring is pure functions over text + profile, so it is unit
  testable and free. An LLM layer (rewriting the report in prose, or extracting
  requirements from messy postings) is a natural next step and would sit *behind* this
  core, not replace it.
- **Persistence is a deployment concern, not a protocol one.** The A2A spec does not
  care where task state lives; the store is injectable so the same app runs correctly
  in-memory on a container and on Postgres behind serverless.
- **The protocol is the product.** The SDK handles the wire format; this repo's job is
  to show a correct card, a correct task lifecycle, and both bindings.
