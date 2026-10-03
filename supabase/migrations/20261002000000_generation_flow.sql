-- Per-idea approval: brief/script first, then image/video generation.
alter table creatives drop constraint creatives_status_check;
alter table creatives add constraint creatives_status_check
  check (status in ('writing','brief_ready','generating','ready','failed','queued','manual'));
alter table videos drop constraint videos_status_check;
alter table videos add constraint videos_status_check
  check (status in ('writing','script_ready','generating','ready','failed','queued','manual'));
alter table ideas drop constraint ideas_status_check;
alter table ideas add constraint ideas_status_check
  check (status in ('proposed','candidate','selected','finalising','finalised','discarded','rejected'));
