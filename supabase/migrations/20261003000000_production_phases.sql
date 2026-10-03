-- The video team's two production steps after the script: the lookbook (agent 4) and the video prompts (agent 5).
--   lookbook        agent 4 is drawing up the lookbook
--   lookbook_ready  the lookbook waits for the manager's approval
--   prompting       agent 5 is writing the video prompts and the Edit Sheet
--   package_ready   the production package is complete; the video can be priced and made
alter table videos drop constraint videos_status_check;
alter table videos add constraint videos_status_check
  check (status in ('writing','script_ready','lookbook','lookbook_ready','prompting','package_ready',
                    'generating','ready','failed','queued','manual'));
