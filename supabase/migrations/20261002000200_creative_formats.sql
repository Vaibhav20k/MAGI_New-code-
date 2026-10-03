-- Progress bars and "Open on Higgsfield": when the current step started, and where Higgsfield keeps the file.
alter table creatives add column if not exists started_at timestamptz;
alter table creatives add column if not exists remote_urls text[] not null default '{}';
alter table videos add column if not exists started_at timestamptz;
alter table videos add column if not exists remote_urls text[] not null default '{}';
