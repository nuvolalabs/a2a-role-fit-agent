-- A2A task persistence for the Role Fit Agent.
--
-- Mirrors the a2a-sdk DatabaseTaskStore layout so this table is interchangeable
-- with the SDK's SQLAlchemy store. Applied via the Supabase Management API:
--
--   POST https://api.supabase.com/v1/projects/<ref>/database/query
--   Authorization: Bearer $SUPABASE_PAT
--   {"query": "<contents of this file>"}

create table if not exists public.a2a_tasks (
    id               text        not null,
    owner            text        not null default '',
    context_id       text,
    kind             text        not null default 'task',
    last_updated     timestamptz,
    status           jsonb,
    artifacts        jsonb,
    history          jsonb,
    task_metadata    jsonb,
    protocol_version text        not null default '1.0',
    primary key (id, owner)
);

create index if not exists a2a_tasks_owner_updated_idx
    on public.a2a_tasks (owner, last_updated desc nulls last);

create index if not exists a2a_tasks_context_idx
    on public.a2a_tasks (context_id);

-- RLS is enabled and NO anon/authenticated policies are created, so the public
-- key cannot read or write task state. The service_role key bypasses RLS, which
-- is what the server uses.
alter table public.a2a_tasks enable row level security;
