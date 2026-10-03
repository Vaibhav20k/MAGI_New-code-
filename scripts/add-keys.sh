#!/bin/bash
# Asks for each key and saves it into .env. Nothing is shown on screen or sent anywhere.
cd "$(dirname "$0")/.." || exit 1
[ -f .env ] || cp .env.example .env

set_key() {
  KEY="$1" VALUE="$2" awk 'BEGIN{k=ENVIRON["KEY"]; v=ENVIRON["VALUE"]; done=0}
    index($0, k"=")==1 {print k"="v; done=1; next} {print}
    END{if(!done) print k"="v}' .env > .env.tmp && mv .env.tmp .env && chmod 600 .env
}

ask() {
  local name="$1" label="$2" secret="$3" current value
  current=$(grep -m1 "^$name=" .env | cut -d= -f2-)
  if [ -n "$current" ]; then status="already saved - press Enter to keep it"; else status="press Enter to skip"; fi
  echo
  echo "$label"
  if [ "$secret" = "yes" ]; then
    read -r -s -p "  Paste here ($status): " value; echo
  else
    read -r -p "  Type here ($status): " value
  fi
  value=$(printf '%s' "$value" | tr -d '[:space:]"'"'")
  if [ -n "$value" ]; then set_key "$name" "$value"; echo "  Saved."; fi
}

ask_text() {
  local name="$1" label="$2" value
  echo; echo "$label"
  read -r -p "  Type here (press Enter to skip): " value
  [ -n "$value" ] && set_key "$name" "$value" && echo "  Saved."
}

# ONLY="KEY1 KEY2" limits the questions to those keys
want() { [ -z "$ONLY" ] && return 0; case " $ONLY " in *" $1 "*) return 0;; esac; return 1; }

echo "=== Marketing MAI: add your keys ==="
echo "Copy a key from the website, click here, press Cmd+V, then Enter."
echo "The key stays hidden while you paste. That is normal."

want GEMINI_API_KEY && ask GEMINI_API_KEY     "1. Gemini key  (aistudio.google.com/apikey)  REQUIRED" yes
want GROQ_API_KEY && ask GROQ_API_KEY       "2. Groq key  (console.groq.com/keys)  REQUIRED" yes
want APIFY_API_TOKEN && ask APIFY_API_TOKEN    "3. Apify token  (console.apify.com/settings/integrations)" yes
want XAI_API_KEY && ask XAI_API_KEY        "4. xAI Grok key  (console.x.ai)  optional, only if free for you" yes
want OPENROUTER_API_KEY && ask OPENROUTER_API_KEY "5. OpenRouter key  (openrouter.ai/settings/keys)  optional" yes
want OPENROUTER_KEY_EVIDENCE && ask OPENROUTER_KEY_EVIDENCE "5a. OpenRouter key for script agent 1, Evidence  (optional: without it the agent uses key 5)" yes
want OPENROUTER_KEY_WRITER && ask OPENROUTER_KEY_WRITER "5b. OpenRouter key for script agent 2, Director-Writer  (optional)" yes
want OPENROUTER_KEY_EDITOR && ask OPENROUTER_KEY_EDITOR "5c. OpenRouter key for script agent 3, Executive Editor  (optional)" yes
want OPENROUTER_KEY_LOOKBOOK && ask OPENROUTER_KEY_LOOKBOOK "5d. OpenRouter key for script agent 4, Lookbook Director  (optional: this agent is not built yet)" yes
want OPENROUTER_KEY_VIDEO_PROMPT && ask OPENROUTER_KEY_VIDEO_PROMPT "5e. OpenRouter key for script agent 5, Video Prompt Engineer  (optional)" yes
want NVIDIA_API_KEY && ask NVIDIA_API_KEY     "6. NVIDIA key  (build.nvidia.com, starts with nvapi-)  optional" yes
want TOKENHARBOR_API_KEY && ask TOKENHARBOR_API_KEY "7. Token Harbor key  (tokenharbor.ai/dashboard/api-keys, starts with thk_live_)" yes
want BLOOM_API_KEY && ask BLOOM_API_KEY "7b. Bloom key  (trybloom.ai, account settings, starts with bloom_sk_)  for creative direction only" yes
want DASHBOARD_PASSWORD && ask DASHBOARD_PASSWORD "8. Dashboard password for the web link  (make up a long one, at least 12 characters, no spaces)" yes
want MANAGER_NAME && ask_text MANAGER_NAME  "9. Name of the manager who approves learnings"

echo
echo "Done. Saved keys:"
for k in GEMINI_API_KEY GROQ_API_KEY APIFY_API_TOKEN XAI_API_KEY OPENROUTER_API_KEY OPENROUTER_KEY_EVIDENCE OPENROUTER_KEY_WRITER OPENROUTER_KEY_EDITOR OPENROUTER_KEY_LOOKBOOK OPENROUTER_KEY_VIDEO_PROMPT NVIDIA_API_KEY TOKENHARBOR_API_KEY BLOOM_API_KEY DASHBOARD_PASSWORD; do
  v=$(grep -m1 "^$k=" .env | cut -d= -f2-)
  if [ -n "$v" ]; then echo "  [x] $k  (${#v} characters)"; else echo "  [ ] $k  (empty)"; fi
done
echo "You can run this again any time to add or change a key."
