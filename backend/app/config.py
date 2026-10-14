from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AI brain — tried in this order, falling back on rate limits or errors
    gemini_api_key: str = ""
    # Tried in order for careful work; each Gemini model has its own free allowance.
    # The larger Gemini models allow only 20 requests a day each on the free plan; the lite model at the end
    # (shared with Cognee) is the fallback. MAI chat uses other lite models (see services/hermes/config.yaml).
    gemini_models: str = "gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash,gemini-3-flash-preview,gemini-3.1-flash-lite"
    gemini_fast_models: str = ""
    # Looking at reference pictures (app/vision.py): models nothing else uses, so the chat and crawler keep theirs
    gemini_vision_models: str = "gemini-3.5-flash-lite,gemini-2.5-flash-lite"
    vision_daily_cap: int = 300
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    cerebras_api_key: str = ""
    cerebras_model: str = "llama-3.3-70b"
    xai_api_key: str = ""
    xai_model: str = "grok-4-fast"
    openrouter_api_key: str = ""
    # named free models, tried in order; "openrouter/free" picks one at random and some of those write junk
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free,qwen/qwen3.8-27b:free"
    # The video team's script engine (backend/script_engine) runs on this one OpenRouter model. Each of its five
    # agents may carry a key of its own; an agent without one uses OPENROUTER_API_KEY.
    script_engine_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    openrouter_key_evidence: str = ""        # agent 1: Evidence and Intelligence
    openrouter_key_writer: str = ""          # agent 2: Director-Writer
    openrouter_key_editor: str = ""          # agent 3: Executive Editor
    openrouter_key_lookbook: str = ""        # agent 4: Lookbook Director (not built yet)
    openrouter_key_video_prompt: str = ""    # agent 5: Video Prompt Engineer
    # NVIDIA (build.nvidia.com): free, limited per minute rather than per day. Models tried in order.
    nvidia_api_key: str = ""
    # measured 2 Oct 2026: the large Nemotron answers in 15 to 40 s when NVIDIA is not overloaded; DeepSeek on NVIDIA
    # queued for two minutes and more, so it is left out
    nvidia_models: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_fast_model: str = "openai/gpt-oss-20b"       # small and quick (about 3 s): the crawler's second brain
    # Token Harbor (tokenharbor.ai): free models, 60 requests a minute, with a weekly free allowance.
    tokenharbor_api_key: str = ""
    tokenharbor_models: str = "deepseek-v4.1-flash:free,qwen3.8-flash:free,mimo-v2.6-flash:free"

    # Bloom (trybloom.ai): the brand's creative direction, read as context only. Images are never made there.
    bloom_api_key: str = ""
    bloom_brand_id: str = ""          # leave empty to use the brand named Magppie

    # Instagram and Facebook reading (apify.com free credit)
    apify_api_token: str = ""

    # Storage
    database_url: str = "postgresql://postgres:postgres@host.docker.internal:54322/postgres"

    # Services inside docker compose
    searxng_url: str = "http://searxng:8080"
    crawl4ai_url: str = "http://crawl4ai:11235"
    crawl4ai_api_token: str = ""
    mcp_token: str = ""
    hermes_api_key: str = ""
    hermes_url: str = "http://hermes:8642"

    # Files
    inputs_dir: Path = Path("/app/inputs")
    data_dir: Path = Path("/app/data")

    # Public web address: the login in front of the dashboard (see app/auth.py)
    dashboard_password: str = ""
    session_secret: str = ""
    public_host: str = ""

    # Manager approval
    manager_name: str = ""
    manager_email: str = ""
    gmail_address: str = ""
    gmail_app_password: str = ""

    # Higgsfield (MCP, OAuth)
    higgsfield_mcp_url: str = "https://mcp.higgsfield.ai/mcp"
    higgsfield_redirect_uri: str = "http://localhost:8000/api/higgsfield/callback"

    # MAI voice (Groq)
    stt_model: str = "whisper-large-v3-turbo"
    tts_model: str = "canopylabs/orpheus-v1-english"
    tts_voice: str = "hannah"
    # Our own voice engine on the server (Kokoro): free, unlimited, private. Tried first.
    kokoro_url: str = "http://voice:8880"
    kokoro_voice: str = "af_heart"          # MAGI is a woman; bf_emma is a British alternative

    cognee_url: str = "http://cognee:8100"

    timezone: str = "Asia/Kolkata"
    embed_model: str = "BAAI/bge-small-en-v1.5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
