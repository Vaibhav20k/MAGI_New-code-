#!/bin/bash
# First start on a new machine: makes .env from .env.example and fills in the internal passwords the
# services use to talk to each other. Your own keys are added afterwards with scripts/add-keys.sh.
# Safe to run again: it never changes a value that is already set.
cd "$(dirname "$0")/.." || exit 1
[ -f .env ] || { cp .env.example .env; echo "Made .env from .env.example."; }
chmod 600 .env

fill() {   # give KEY a random value if it is empty or missing
  local key="$1" current
  current=$(grep -m1 "^$key=" .env | cut -d= -f2-)
  [ -n "$current" ] && return
  KEY="$key" VALUE="$(openssl rand -hex 24)" awk 'BEGIN{k=ENVIRON["KEY"]; v=ENVIRON["VALUE"]; done=0}
    index($0, k"=")==1 {print k"="v; done=1; next} {print}
    END{if(!done) print k"="v}' .env > .env.tmp && mv .env.tmp .env && chmod 600 .env
  echo "  set $key"
}

echo "Internal passwords:"
for key in SEARXNG_SECRET CRAWL4AI_API_TOKEN HERMES_API_KEY MCP_TOKEN SESSION_SECRET; do fill "$key"; done
echo "Done. Next: bash scripts/add-keys.sh, then: docker compose up -d --build"
