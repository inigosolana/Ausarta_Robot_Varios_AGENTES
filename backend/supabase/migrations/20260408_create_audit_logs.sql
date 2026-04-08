-- Audit log table for security-sensitive actions (hidden/internal use)
create table if not exists public.audit_logs (
  id bigserial primary key,
  user_id uuid null,
  action text not null,
  target_type text not null,
  target_id text not null,
  "timestamp" timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists idx_audit_logs_user_id on public.audit_logs (user_id);
create index if not exists idx_audit_logs_timestamp on public.audit_logs ("timestamp" desc);
create index if not exists idx_audit_logs_action on public.audit_logs (action);
create index if not exists idx_audit_logs_target on public.audit_logs (target_type, target_id);

-- Optional hardening hint:
-- revoke all on table public.audit_logs from anon, authenticated;
-- grant select, insert on public.audit_logs to service_role;
