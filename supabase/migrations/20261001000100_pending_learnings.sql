-- A safe learning seen on only one source waits as 'pending' until a second source confirms it.
alter table learnings drop constraint learnings_status_check;
alter table learnings add constraint learnings_status_check
  check (status in ('pending','active','held','approved','rejected','expired','discarded'));

-- Crawl queue, so a night run can be stopped and resumed
create table crawl_queue (
  url         text primary key,
  depth       int not null default 0,
  priority    real not null default 0,
  source_id   bigint references sources(id) on delete set null,
  reason      text,
  added_at    timestamptz not null default now()
);
create index crawl_queue_priority_idx on crawl_queue (priority desc, added_at);
