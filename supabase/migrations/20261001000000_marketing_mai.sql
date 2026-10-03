-- Marketing MAI — core schema
-- Embeddings: 384 dims (BAAI/bge-small-en-v1.5, runs locally, free and unlimited)

create extension if not exists vector;
create extension if not exists pg_trgm;

-- ---------- Crawling ----------

create table sources (
  id               bigint generated always as identity primary key,
  url              text not null unique,
  domain           text not null,
  kind             text not null default 'website'
                   check (kind in ('website','youtube_channel','youtube_video','instagram','linkedin','pinterest','facebook','other')),
  status           text not null default 'discovered'
                   check (status in ('seed','discovered','trusted','blocked')),
  score            real not null default 0,          -- how relevant this source keeps proving
  discovered_from  bigint references sources(id) on delete set null,
  notes            text,
  created_at       timestamptz not null default now(),
  last_crawled_at  timestamptz
);
create index sources_domain_idx on sources (domain);
create index sources_status_idx on sources (status);

create table crawl_runs (
  id          bigint generated always as identity primary key,
  trigger     text not null default 'schedule' check (trigger in ('schedule','manual')),
  status      text not null default 'running' check (status in ('running','stopped','finished','failed')),
  started_at  timestamptz not null default now(),
  ended_at    timestamptz,
  stats       jsonb not null default '{}'::jsonb   -- pages_seen, pages_kept, learnings, held, new_sources ...
);

create table pages (
  id            bigint generated always as identity primary key,
  url           text not null unique,
  source_id     bigint references sources(id) on delete set null,
  run_id        bigint references crawl_runs(id) on delete set null,
  title         text,
  content_md    text,
  content_hash  text,
  published_at  timestamptz,
  fetched_at    timestamptz not null default now(),
  relevance     real,
  kept          boolean not null default false,
  processed     boolean not null default false,       -- knowledge agent has read it
  meta          jsonb not null default '{}'::jsonb      -- views, likes, channel, transcript flag ...
);
create index pages_hash_idx on pages (content_hash);
create index pages_unprocessed_idx on pages (kept, processed) where kept and not processed;

-- ---------- Knowledge base ----------

create table kb_chunks (
  id          bigint generated always as identity primary key,
  doc         text not null check (doc in ('core','script_bank','brand','learned','manager')),
  section     text,
  content     text not null,
  embedding   vector(384),
  meta        jsonb not null default '{}'::jsonb,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);
create index kb_chunks_embedding_idx on kb_chunks using hnsw (embedding vector_cosine_ops);
create index kb_chunks_doc_idx on kb_chunks (doc) where active;

create table learnings (
  id              bigint generated always as identity primary key,
  run_id          bigint references crawl_runs(id) on delete set null,
  content         text not null,
  kind            text not null default 'trend'
                  check (kind in ('trend','hook','format','keyword','pain_point','competitor_post','industry_fact','engagement','new_source','other')),
  bucket          text not null check (bucket in ('auto','hold','never')),
  status          text not null
                  check (status in ('active','held','approved','rejected','expired','discarded')),
  rule            text,                         -- which approval rule put it in this bucket
  affects         text,                         -- what in the KB it touches or contradicts
  source_urls     text[] not null default '{}',
  source_count    int not null default 1,
  confidence      real not null default 0.5,
  embedding       vector(384),
  edited_content  text,
  manager_note    text,
  expires_at      timestamptz,
  created_at      timestamptz not null default now(),
  reviewed_at     timestamptz
);
create index learnings_status_idx on learnings (status);
create index learnings_embedding_idx on learnings using hnsw (embedding vector_cosine_ops);

create table manager_rules (
  id          bigint generated always as identity primary key,
  kind        text not null check (kind in ('add_knowledge','never_use','block_site','trust_site')),
  content     text not null,
  created_at  timestamptz not null default now()
);

create table review_sessions (
  id            bigint generated always as identity primary key,
  finalised_at  timestamptz not null default now(),
  approved      int not null default 0,
  rejected      int not null default 0,
  edited        int not null default 0,
  added         int not null default 0
);

-- ---------- Ideas and content ----------

create table idea_batches (
  id          bigint generated always as identity primary key,
  created_at  timestamptz not null default now(),
  status      text not null default 'running' check (status in ('running','ready','failed')),
  error       text
);

create table ideas (
  id           bigint generated always as identity primary key,
  batch_id     bigint references idea_batches(id) on delete cascade,
  type         text not null check (type in ('blog','creative','video')),
  title        text not null,
  summary      text,
  angle        text,                              -- why it fits Magppie
  inspired_by  jsonb not null default '[]'::jsonb, -- [{url,title,signal}]
  kb_refs      jsonb not null default '[]'::jsonb, -- KB passages used
  payload      jsonb not null default '{}'::jsonb, -- type-specific draft (brief, hook, scenes ...)
  score        real,
  status       text not null default 'proposed'
               check (status in ('proposed','candidate','selected','finalising','finalised','discarded')),
  embedding    vector(384),
  created_at   timestamptz not null default now()
);
create index ideas_status_idx on ideas (status);
create index ideas_embedding_idx on ideas using hnsw (embedding vector_cosine_ops);

create table blogs (
  id                bigint generated always as identity primary key,
  idea_id           bigint references ideas(id) on delete set null,
  title             text not null,
  meta_description  text,
  focus_keyword     text,
  body_md           text not null,
  sources           jsonb not null default '[]'::jsonb,
  created_at        timestamptz not null default now()
);

create table creatives (
  id           bigint generated always as identity primary key,
  idea_id      bigint references ideas(id) on delete set null,
  brief        jsonb not null,
  image_urls   text[] not null default '{}',
  status       text not null default 'queued' check (status in ('queued','generating','ready','failed','manual')),
  job_ids      text[] not null default '{}',
  error        text,
  created_at   timestamptz not null default now()
);

create table videos (
  id          bigint generated always as identity primary key,
  idea_id     bigint references ideas(id) on delete set null,
  script      jsonb not null,
  video_urls  text[] not null default '{}',
  status      text not null default 'queued' check (status in ('queued','generating','ready','failed','manual')),
  job_ids     text[] not null default '{}',
  error       text,
  created_at  timestamptz not null default now()
);

-- ---------- App ----------

create table notifications (
  id          bigint generated always as identity primary key,
  kind        text not null,
  title       text not null,
  body        text,
  read        boolean not null default false,
  created_at  timestamptz not null default now()
);

create table settings (
  key    text primary key,
  value  jsonb not null
);

insert into settings (key, value) values
  ('crawl_window',   '{"start":"20:00","end":"08:00","tz":"Asia/Kolkata"}'),
  ('review_time',    '{"time":"18:00","tz":"Asia/Kolkata"}'),
  ('crawl_limits',   '{"max_depth":3,"per_domain_delay_s":3,"relevance_threshold":0.05,"max_pages_per_run":30000}'),
  ('hold_auto_reject_days', '14'),
  ('trend_expiry_days', '60');

-- ---------- Search helpers ----------

create or replace function match_kb(query_embedding vector(384), match_count int default 8, docs text[] default null)
returns table (id bigint, doc text, section text, content text, meta jsonb, similarity real)
language sql stable as $$
  select k.id, k.doc, k.section, k.content, k.meta, (1 - (k.embedding <=> query_embedding))::real as similarity
  from kb_chunks k
  where k.active and (docs is null or k.doc = any(docs))
  order by k.embedding <=> query_embedding
  limit match_count;
$$;

create or replace function similar_ideas(query_embedding vector(384), match_count int default 5)
returns table (id bigint, title text, type text, status text, similarity real)
language sql stable as $$
  select i.id, i.title, i.type, i.status, (1 - (i.embedding <=> query_embedding))::real
  from ideas i
  where i.embedding is not null
  order by i.embedding <=> query_embedding
  limit match_count;
$$;

create or replace function similar_learnings(query_embedding vector(384), match_count int default 5)
returns table (id bigint, content text, status text, similarity real)
language sql stable as $$
  select l.id, coalesce(l.edited_content, l.content), l.status, (1 - (l.embedding <=> query_embedding))::real
  from learnings l
  where l.embedding is not null
  order by l.embedding <=> query_embedding
  limit match_count;
$$;
