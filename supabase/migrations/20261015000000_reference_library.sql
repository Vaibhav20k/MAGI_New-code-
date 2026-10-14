-- The reference library: MAGPPIE's own pictures and clips (finishes, kitchens, vanities, wardrobes, the logo),
-- copied from the shared Drive folder, described, and searchable by meaning for lookbooks and videos.
-- Safe to run more than once.

create table if not exists ref_assets (
  id                     bigserial primary key,
  drive_id               text unique,                         -- null for pictures MAGI made itself
  path                   text not null default '',            -- the Drive folder it came from
  name                   text not null,
  kind                   text not null check (kind in ('finish','kitchen','vanity','wardrobe','video','logo','frame','other')),
  source                 text check (source in ('real','render','generated')),
  media_type             text not null default 'image' check (media_type in ('image','video')),
  finish                 text,                                -- the finish's official name, when known
  finish_from            text check (finish_from in ('file','guess','person')),
  layout                 text,
  room                   text,
  colours                text[] not null default '{}',
  description            text,                                -- internal catalogue text, never published
  tags                   text[] not null default '{}',
  flags                  jsonb not null default '{}',         -- people, wood_or_steel_look, text_or_logo
  file_path              text,                                -- under /media
  thumb_path             text,
  width                  int,
  height                 int,
  bytes                  bigint,
  higgsfield_media_id    text,                                -- kept so a file is uploaded to Higgsfield once
  higgsfield_uploaded_at timestamptz,
  reviewed               boolean not null default false,      -- a person has checked the finish and tags
  usable_as              text not null default 'exact' check (usable_as in ('exact','style')),
  active                 boolean not null default true,       -- false once it disappears from the Drive
  described_at           timestamptz,
  embedding              vector(384),
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
create index if not exists ref_assets_embedding_idx on ref_assets using hnsw (embedding vector_cosine_ops);
create index if not exists ref_assets_kind_idx on ref_assets (kind) where active;

-- Which reference went into which video or creative, so the next one can choose differently.
create table if not exists ref_uses (
  id          bigserial primary key,
  ref_id      bigint not null references ref_assets(id) on delete cascade,
  video_id    bigint references videos(id) on delete cascade,
  creative_id bigint references creatives(id) on delete cascade,
  role        text not null,                                  -- kitchen, finish, frame, start_image ...
  used_at     timestamptz not null default now()
);
create index if not exists ref_uses_recent_idx on ref_uses (used_at desc);

create or replace function match_refs(q vector(384), match_count int, kinds text[] default null)
returns table (id bigint, kind text, name text, finish text, layout text, source text, reviewed boolean,
               usable_as text, thumb_path text, file_path text, description text, similarity real)
language sql stable as $$
  select r.id, r.kind, r.name, r.finish, r.layout, r.source, r.reviewed, r.usable_as, r.thumb_path, r.file_path,
         r.description, (1 - (r.embedding <=> q))::real as similarity
  from ref_assets r
  where r.active and r.embedding is not null and (kinds is null or r.kind = any(kinds))
  order by r.embedding <=> q
  limit match_count
$$;
