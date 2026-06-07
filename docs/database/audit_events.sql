create table if not exists audit_events (
  sequence_id bigserial primary key,
  chain_scope text not null,
  chain_id text not null,
  event_id text not null unique,
  event_type text not null,
  occurred_at timestamptz not null,
  inserted_at timestamptz not null default now(),

  run_id text not null,
  process_name text not null,
  process_version text,
  process_hash text,
  node_id text,
  node_type text,

  actor_id text,
  actor_type text,
  policy_id text,
  correlation_id text,
  external_ref text,

  trace_id text,
  span_id text,

  payload jsonb not null,
  payload_sha256 text not null,
  previous_hash text,
  event_hash text not null
);

create index if not exists audit_events_chain_idx
  on audit_events (chain_scope, chain_id, sequence_id);

create index if not exists audit_events_run_idx
  on audit_events (run_id, sequence_id);

create or replace function bpg_prevent_audit_events_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'audit_events is append-only and cannot be updated or deleted';
end;
$$;

drop trigger if exists audit_events_no_update on audit_events;
create trigger audit_events_no_update
before update on audit_events
for each row execute function bpg_prevent_audit_events_mutation();

drop trigger if exists audit_events_no_delete on audit_events;
create trigger audit_events_no_delete
before delete on audit_events
for each row execute function bpg_prevent_audit_events_mutation();
