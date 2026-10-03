-- Team-only knowledge (IPO, valuation, hiring, internal systems): MAGI may tell the team,
-- the agents that write public content never see it.
alter table kb_chunks drop constraint kb_chunks_doc_check;
alter table kb_chunks add constraint kb_chunks_doc_check
  check (doc in ('core','script_bank','brand','learned','manager','internal'));
