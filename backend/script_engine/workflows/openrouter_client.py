import json
import time
import logging
import re
from typing import Dict, Any, Optional, List
import httpx
from workflows.config import EngineConfig

logger = logging.getLogger("MagppieEngine.OpenRouterClient")

class OpenRouterError(Exception):
    """Exception raised for OpenRouter API errors."""
    pass

class OpenRouterRateLimitError(OpenRouterError):
    """Exception raised specifically when upstream model is rate limited (429)."""
    pass

class OpenRouterClient:
    """Client for OpenRouter API with retry, logging, and JSON extraction."""

    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    # Hard ceiling for a recovery retry. The pinned model advertises
    # 235,929 max completion tokens; this stays well inside it.
    MAX_OUTPUT_TOKENS = 96000

    def __init__(self, config: EngineConfig):
        self.config = config
        self.api_key = config.openrouter_api_key
        self.model = config.model_name
        self.timeout = config.timeout_seconds
        self.max_retries = config.max_retries

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def _response_format(
        self, response_schema: Optional[Dict[str, Any]], schema_name: str
    ) -> Dict[str, Any]:
        """
        Prefer provider-side schema enforcement so the schema does not have to be
        pasted into the prompt. Models without structured-output support fall back
        to plain JSON mode; local jsonschema validation remains the real gate
        either way, since strict mode is not guaranteed across free providers.
        """
        if response_schema and self.config.supports_structured_outputs:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": False,
                    "schema": response_schema,
                },
            }
        return {"type": "json_object"}

    def call_model(
        self, system_instruction: str, user_prompt: str,
        temperature: Optional[float] = None, max_tokens: Optional[int] = None,
        agent_name: str = "unknown", run_id: str = "run-unknown",
        response_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "artifact",
        seed: Optional[int] = None,
        reasoning_tokens: int = 0
    ) -> Dict[str, Any]:
        """Regenerate once on truncated/malformed output; never repair missing claims."""
        started = time.time()
        budget = max_tokens if max_tokens is not None else self.config.max_tokens
        totals = {}
        for output_attempt in range(2):
            response = self._request_model(system_instruction, user_prompt, temperature,
                                           budget, agent_name, run_id,
                                           response_schema=response_schema,
                                           schema_name=schema_name, seed=seed,
                                           reasoning_tokens=reasoning_tokens)
            for key, value in response["usage"].items():
                if isinstance(value, (int, float)):
                    totals[key] = totals.get(key, 0) + value
            reason = response.get("finish_reason")
            problem = None
            if reason == "length":
                problem = "response reached its token limit"
            elif reason not in (None, "stop"):
                raise OpenRouterError(f"{agent_name} did not complete (finish reason: {reason}). No script was accepted.")
            else:
                try:
                    response["parsed_json"] = self.extract_json(response["content"])
                    if not isinstance(response["parsed_json"], dict):
                        problem = "response was not a JSON object"
                except OpenRouterError:
                    problem = "response contained incomplete or invalid JSON"
            if problem is None:
                response["usage"] = totals
                response["latency_seconds"] = round(time.time() - started, 3)
                response["status"] = "SUCCESS"
                return response
            logger.warning("[%s] %s: %s (output attempt %s/2, finish_reason=%s)",
                           run_id, agent_name, problem, output_attempt + 1, reason)
            if output_attempt == 1:
                raise OpenRouterError(
                    f"{agent_name} returned incomplete or invalid output after one recovery retry. "
                    "Completed research and draft artifacts remain saved. No final script was accepted."
                )
            # Grow from the caller's own ceiling. A flat cap here silently
            # undid per-agent budgets and turned a truncation into a dead run.
            budget = min(budget * 2, self.MAX_OUTPUT_TOKENS)
            user_prompt += ("\nOUTPUT RECOVERY: The previous response was incomplete or invalid JSON. "
                            "Regenerate the complete JSON object from the original inputs. "
                            "Keep explanations concise, include every required field, escape quotation marks "
                            "inside strings, and finish all arrays and objects. Do not return a continuation "
                            "or invent facts to fill gaps.")

    def _request_model(
        self,
        system_instruction: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        agent_name: str = "unknown",
        run_id: str = "run-unknown",
        response_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "artifact",
        seed: Optional[int] = None,
        reasoning_tokens: int = 0
    ) -> Dict[str, Any]:
        """
        Calls OpenRouter API with retries and structured logging.
        Returns a dict containing response text, usage metadata, and latency.
        """
        if not self.is_available():
            raise OpenRouterError(
                "OPENROUTER_API_KEY is not configured in the environment or .env file."
            )

        if self.config.model_provider != "openrouter" or not (
            self.model.endswith(":free") and not self.model.startswith("openrouter/")
            or self.model == "openrouter/free"
        ):
            raise OpenRouterError("Free-model-only policy: select a specific :free model or openrouter/free.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://magppie.com/content-engine",
            "X-Title": "Magppie Content Intelligence Engine",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "provider": {"max_price": {"prompt": 0, "completion": 0}},
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature if temperature is not None else self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            "response_format": self._response_format(response_schema, schema_name),
        }

        # Only models that advertise seed support accept this parameter.
        if seed is not None and self.config.supports_seed:
            payload["seed"] = seed

        # Budget the thinking phase rather than removing it. Reasoning is what makes
        # Agent 1 evaluate sources instead of pattern-matching, but left unbounded it
        # dominated the run: 15,734 completion tokens for a 1,338-token dossier.
        if reasoning_tokens and self.config.supports_reasoning:
            payload["reasoning"] = {"max_tokens": reasoning_tokens}

        start_time = time.time()
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    f"[{run_id}] Calling model for Agent: '{agent_name}' (Model: {self.model}, Attempt: {attempt}/{self.max_retries})"
                )
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(self.BASE_URL, headers=headers, json=payload)

                latency = round(time.time() - start_time, 3)

                if response.status_code == 200:
                    resp_json = response.json()

                    # OpenRouter reports upstream provider failures as an `error`
                    # object inside a 200 response, not as an HTTP error code. Left
                    # unhandled these surfaced as "empty choices array" and skipped
                    # the retry path entirely, so one transient overload killed a run.
                    upstream = resp_json.get("error")
                    if upstream:
                        message = upstream.get("message") or "Unknown upstream error"
                        code = upstream.get("code")
                        kind = (upstream.get("metadata") or {}).get("error_type", "")
                        transient = code in (429, 500, 502, 503, 504) or kind in (
                            "provider_overloaded", "rate_limited"
                        )
                        if not transient:
                            raise OpenRouterError(f"{self.model} rejected the request: {message}")
                        logger.warning(
                            f"[{run_id}] Upstream {code or 'error'} for '{agent_name}': {message} "
                            f"(attempt {attempt}/{self.max_retries})"
                        )
                        last_error = (OpenRouterRateLimitError if code == 429 else OpenRouterError)(
                            f"Upstream {code or 'error'}: {message}"
                        )
                        if attempt < self.max_retries:
                            time.sleep(min(attempt * 3, 15))
                            continue
                        raise last_error

                    choices = resp_json.get("choices", [])
                    if not choices:
                        raise OpenRouterError("OpenRouter returned no choices and no error.")

                    content = choices[0].get("message", {}).get("content")
                    if (not isinstance(content, str) or not content.strip()) and choices[0].get("finish_reason") != "length":
                        raise OpenRouterError("The free model returned no script content. Please retry later; no demo output was substituted.")
                    content = (content or "").strip()
                    usage = resp_json.get("usage", {})

                    logger.info(
                        f"[{run_id}] Agent: '{agent_name}' response received (Latency: {latency}s, "
                        f"PromptTokens: {usage.get('prompt_tokens', 0)}, "
                        f"CompletionTokens: {usage.get('completion_tokens', 0)}, "
                        f"ReasoningTokens: {(usage.get('completion_tokens_details') or {}).get('reasoning_tokens', 0)})"
                    )

                    return {
                        "content": content,
                        "finish_reason": choices[0].get("finish_reason"),
                        "latency_seconds": latency,
                        "usage": usage,
                        "model": self.model,
                        "status": "SUCCESS"
                    }

                elif response.status_code == 429:
                    error_text = response.text
                    logger.warning(
                        f"[{run_id}] OpenRouter rate limit 429 encountered: {error_text}"
                    )
                    last_error = OpenRouterRateLimitError(f"HTTP 429: {error_text}")
                    if attempt < self.max_retries:
                        time.sleep(attempt * 1.5)
                    else:
                        raise OpenRouterRateLimitError(f"Upstream rate limit 429: {error_text}")

                elif response.status_code in [500, 502, 503, 504]:
                    error_text = response.text
                    logger.warning(
                        f"[{run_id}] Transient API error (Status {response.status_code}): {error_text}. Retrying in {attempt}s..."
                    )
                    time.sleep(attempt)
                    last_error = OpenRouterError(f"HTTP {response.status_code}: {error_text}")
                else:
                    error_text = response.text
                    logger.error(f"[{run_id}] Fatal API error (Status {response.status_code}): {error_text}")
                    raise OpenRouterError(f"Fatal API error ({response.status_code}): {error_text}")

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                logger.warning(f"[{run_id}] Network/Timeout exception on attempt {attempt}: {str(e)}")
                time.sleep(attempt)
                last_error = e
            except OpenRouterRateLimitError:
                raise
            except Exception as e:
                logger.error(f"[{run_id}] Unexpected error in OpenRouter call: {str(e)}")
                raise

        raise OpenRouterError(f"Max retries exceeded ({self.max_retries}). Last error: {last_error}")

    @staticmethod
    def extract_json(content: str) -> Dict[str, Any]:
        """Extracts and parses JSON from raw or markdown-wrapped LLM text."""
        cleaned = content.strip()

        # Handle ```json ... ``` code blocks
        json_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if json_block_match:
            cleaned = json_block_match.group(1).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            # Attempt to locate first { and last }
            first_brace = cleaned.find("{")
            last_brace = cleaned.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                substring = cleaned[first_brace : last_brace + 1]
                try:
                    return json.loads(substring)
                except json.JSONDecodeError:
                    pass
            raise OpenRouterError(f"Failed to parse complete JSON from model response: {e}")
