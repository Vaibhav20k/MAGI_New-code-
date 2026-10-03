import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional
from dotenv import load_dotenv

# Free-tier default. Chosen because it is the only :free model on OpenRouter that
# supports json_object AND structured_outputs AND seed together, which this
# pipeline needs for schema-enforced handoffs and per-run reproducibility.
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

# Known-good fallback: same JSON capabilities, no seed support.
FALLBACK_MODEL = "dots-studio/dots-3-note-preview:free"

# Models that accept a JSON Schema via response_format. Anything absent here
# degrades to plain json_object plus a compact schema outline in the prompt.
STRUCTURED_OUTPUT_MODELS = frozenset({
    "nvidia/nemotron-3-super-120b-a12b:free",
    "dots-studio/dots-3-note-preview:free",
    "qwen/qwen3.8-27b:free",
})

# Models that accept a `seed` parameter. Sending one to a model that does not
# support it is rejected by some providers, so this gate stays explicit.
SEED_CAPABLE_MODELS = frozenset({
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
})

# Agent 1 and Agent 2 need sampling headroom, or every run retraces the same
# argmax path and produces the same hook. Agent 3 is a gate and stays stable.
DEFAULT_AGENT_TEMPERATURES = {
    "agent1": 0.85,
    "agent2": 0.9,
    "agent3": 0.2,
    "agent4": 0.6,    # the lookbook is a visual interpretation: some room, inside a locked script
    "agent5": 0.3,    # the video prompts implement an approved plan: little room
}

# Output ceilings per agent. Agent 2 writes the whole directed script — continuity
# bible, ten direction fields and five timed beats for every 30-second scene — so it
# needs far more room than the others. A 60-second script blew a flat 20,000-token
# ceiling mid-write and the run failed outright.
DEFAULT_AGENT_MAX_TOKENS = {
    "agent1": 24000,
    "agent2": 64000,
    "agent3": 40000,
    "agent4": 32000,
    "agent5": 24000,
}

# Models that accept OpenRouter's `reasoning` parameter.
REASONING_CAPABLE_MODELS = frozenset({
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "dots-studio/dots-3-note-preview:free",
    "qwen/qwen3.8-27b:free",
    "thinkingmachines/inkling:free",
})

# Reasoning is kept, not removed — it is what makes Agent 1 evaluate sources
# instead of pattern-matching. It is *budgeted*, because the measured problem was
# an unbounded thinking phase: Agent 1 spent 15,734 completion tokens and 211s to
# emit a 1,338-token dossier, and an earlier attempt burned 271s hitting the
# ceiling mid-thought without producing anything at all.
DEFAULT_AGENT_REASONING_TOKENS = {
    "agent1": 4000,   # source evaluation and claim classification: the most to think about
    "agent2": 3000,   # angle selection and self-critique
    "agent3": 3000,   # QA passes; it caught an unsupported claim at this budget
    "agent4": 3000,   # choosing the key moment and the look of each frame
    "agent5": 2500,   # translating approved beats into visible action
}


@dataclass
class EngineConfig:
    project_root: Path
    openrouter_api_key: Optional[str]
    model_provider: str
    model_name: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    max_retries: int
    runs_dir: Path
    schemas_dir: Path
    agents_dir: Path
    knowledge_dir: Path
    top_p: float = 0.95
    agent_temperatures: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_AGENT_TEMPERATURES)
    )
    agent_reasoning_tokens: Dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_AGENT_REASONING_TOKENS)
    )
    agent_max_tokens: Dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_AGENT_MAX_TOKENS)
    )
    enable_agent1_web_search: bool = False

    @property
    def is_api_configured(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_api_key.strip())

    @property
    def supports_structured_outputs(self) -> bool:
        return self.model_name in STRUCTURED_OUTPUT_MODELS

    @property
    def supports_seed(self) -> bool:
        return self.model_name in SEED_CAPABLE_MODELS

    @property
    def supports_reasoning(self) -> bool:
        return self.model_name in REASONING_CAPABLE_MODELS

    def max_tokens_for(self, agent_key: str) -> int:
        """Output ceiling for one agent, falling back to the global setting."""
        return self.agent_max_tokens.get(agent_key, self.max_tokens)

    def reasoning_tokens_for(self, agent_key: str) -> int:
        """0 disables the budget and lets the model think without a ceiling."""
        return self.agent_reasoning_tokens.get(agent_key, 0)

    def temperature_for(self, agent_key: str) -> float:
        """Per-agent sampling temperature, falling back to the global setting."""
        return self.agent_temperatures.get(agent_key, self.temperature)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip().strip("'\"")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().strip("'\"").lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def load_config(root_path: Optional[Path] = None) -> EngineConfig:
    """Loads configuration from environment variables and .env file."""
    if root_path is None:
        root_path = Path(__file__).resolve().parent.parent

    # Load .env file from project root if it exists
    env_file = root_path / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=True)

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip() or None
    provider = os.getenv("MODEL_PROVIDER", "openrouter").strip().strip("'\"")
    model_name = os.getenv("MODEL_NAME", DEFAULT_MODEL).strip().strip("'\"")

    global_temperature = _env_float("MODEL_TEMPERATURE", 0.7)
    agent_temperatures = {
        key: _env_float(f"{key.upper()}_TEMPERATURE", DEFAULT_AGENT_TEMPERATURES[key])
        for key in DEFAULT_AGENT_TEMPERATURES
    }
    agent_reasoning = {
        key: int(_env_float(f"{key.upper()}_REASONING_TOKENS",
                            DEFAULT_AGENT_REASONING_TOKENS[key]))
        for key in DEFAULT_AGENT_REASONING_TOKENS
    }
    agent_max = {
        key: int(_env_float(f"{key.upper()}_MAX_TOKENS", DEFAULT_AGENT_MAX_TOKENS[key]))
        for key in DEFAULT_AGENT_MAX_TOKENS
    }

    return EngineConfig(
        project_root=root_path,
        openrouter_api_key=api_key,
        model_provider=provider,
        model_name=model_name,
        temperature=global_temperature,
        agent_temperatures=agent_temperatures,
        agent_reasoning_tokens=agent_reasoning,
        agent_max_tokens=agent_max,
        top_p=_env_float("MODEL_TOP_P", 0.95),
        # Must comfortably exceed the largest reasoning budget plus a full artifact.
        # At 4096 against a 4000-token reasoning budget, a fresh install with no .env
        # would truncate every Agent 1 call mid-thought and pay the retry twice.
        max_tokens=int(os.getenv("MODEL_MAX_TOKENS", "20000").strip().strip("'\"")),
        timeout_seconds=int(os.getenv("MODEL_TIMEOUT_SECONDS", "10").strip().strip("'\"")),
        max_retries=int(os.getenv("MODEL_MAX_RETRIES", "1").strip().strip("'\"")),
        enable_agent1_web_search=_env_bool("ENABLE_AGENT1_WEB_SEARCH", False),
        runs_dir=root_path / "runs",
        schemas_dir=root_path / "schemas",
        agents_dir=root_path / "agents",
        knowledge_dir=root_path / "knowledge",
    )
