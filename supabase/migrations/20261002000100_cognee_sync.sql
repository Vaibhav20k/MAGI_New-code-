-- Which learnings and KB passages have been handed to Cognee (the connected-knowledge map)
alter table learnings add column if not exists cognee_synced_at timestamptz;
alter table kb_chunks add column if not exists cognee_synced_at timestamptz;
insert into settings (key, value) values ('cognee_budget', '{"kb_passages_per_run": 150, "learnings_per_run": 300}')
  on conflict (key) do nothing;
