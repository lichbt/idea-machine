"""LLM wrapper that enforces valid-JSON responses with retries.

Backend order is set by config.LLM_BACKEND (default "auto"): a configured
OpenAI-compatible endpoint (LLM_BASE_URL/LLM_API_KEY, or OPENROUTER_*) is
preferred, with the Claude CLI (`claude -p`) as the fallback; "cli"/"openai"
force a single backend. JSON-parsing retries sit on top of whichever backend
produced the text.

Invariant: the pipeline never crashes on a single bad response. After
CLAUDE_MAX_RETRIES failed parses, raises ClaudeJSONError so the caller can mark
the item failed and continue.
"""
import json
import logging
import re
import subprocess

import requests

import config

log = logging.getLogger(__name__)

_JSON_INSTRUCTION = (
    "Respond ONLY with valid JSON. No markdown, no explanation, no backticks."
)

# Caches so we don't probe a missing CLI on every single call.
_cli_available = None


class ClaudeJSONError(Exception):
    """Raised when the model fails to return parseable JSON after all retries."""


class BackendError(Exception):
    """Raised when a backend (CLI or OpenRouter) cannot produce any text."""


def _strip_to_json(text):
    """Best-effort extraction of a JSON object/array from a model response."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not (text.startswith("{") or text.startswith("[")):
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if match:
            text = match.group(1)
    return text


def _cli_present():
    """Probe (once) whether the Claude CLI binary is on PATH and runnable."""
    global _cli_available
    if _cli_available is not None:
        return _cli_available
    try:
        subprocess.run(
            [config.CLAUDE_CLI_BIN, "--version"],
            capture_output=True, text=True, timeout=15,
        )
        _cli_available = True
    except (OSError, subprocess.SubprocessError) as e:
        log.info("Claude CLI not available (%s); will use OpenRouter", e)
        _cli_available = False
    return _cli_available


def _complete_via_cli(prompt, system, model):
    """One-shot completion via `claude -p`. Returns text or raises BackendError."""
    cmd = [config.CLAUDE_CLI_BIN, "-p", prompt, "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    if system:
        cmd += ["--append-system-prompt", system]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=config.CLAUDE_CLI_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise BackendError(f"Claude CLI invocation failed: {e}")
    if result.returncode != 0:
        raise BackendError(
            f"Claude CLI exited {result.returncode}: {result.stderr.strip()[:300]}"
        )
    out = (result.stdout or "").strip()
    if not out:
        raise BackendError("Claude CLI returned empty output")
    return out


def _openai_settings():
    """Resolve the active OpenAI-compatible endpoint (base_url, key, model), or
    None if none is configured. A custom LLM_* gateway wins over OPENROUTER_*."""
    if config.LLM_API_KEY and config.LLM_BASE_URL:
        return (config.LLM_BASE_URL, config.LLM_API_KEY,
                config.LLM_MODEL or config.OPENROUTER_MODEL)
    if config.OPENROUTER_API_KEY:
        return ("https://openrouter.ai/api/v1", config.OPENROUTER_API_KEY,
                config.OPENROUTER_MODEL)
    return None


def _extract_content(resp):
    """Pull the assistant text out of a chat-completions response, tolerating
    both plain JSON and SSE streaming (text/event-stream) bodies — some gateways
    stream regardless of the stream flag."""
    ctype = resp.headers.get("content-type", "")
    text = resp.text
    if "text/event-stream" in ctype or text.lstrip().startswith("data:"):
        parts = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choice = (obj.get("choices") or [{}])[0]
            piece = ((choice.get("delta") or {}).get("content")
                     or (choice.get("message") or {}).get("content") or "")
            if piece:
                parts.append(piece)
        return "".join(parts).strip()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _complete_via_openai(settings, prompt, system, max_tokens):
    """Completion via any OpenAI-compatible /chat/completions endpoint.
    Returns text or raises BackendError."""
    base_url, api_key, model = settings
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": messages, "stream": False}
    if max_tokens:
        body["max_tokens"] = max_tokens
    url = base_url.rstrip("/") + "/chat/completions"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=config.CLAUDE_CLI_TIMEOUT,
        )
        resp.raise_for_status()
        content = _extract_content(resp)
        if not content:
            raise BackendError("empty content from endpoint")
        return content
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        raise BackendError(f"OpenAI-compatible request to {url} failed: {e}")


def _backend_order():
    """Decide which backends to try, in order, from LLM_BACKEND + what's set."""
    openai_set = _openai_settings() is not None
    if config.LLM_BACKEND == "cli":
        return ["cli"]
    if config.LLM_BACKEND == "openai":
        return ["openai"]
    # auto: prefer the configured OpenAI-compatible endpoint, CLI as fallback.
    return ["openai", "cli"] if openai_set else ["cli"]


def _complete(prompt, system, max_tokens=None):
    """Get raw text from the first backend that succeeds, in configured order."""
    errs = {}
    for backend in _backend_order():
        try:
            if backend == "cli":
                if not _cli_present():
                    raise BackendError("Claude CLI not available")
                return _complete_via_cli(prompt, system, config.CLAUDE_CLI_MODEL)
            settings = _openai_settings()
            if not settings:
                raise BackendError("no OpenAI-compatible endpoint configured")
            return _complete_via_openai(settings, prompt, system, max_tokens)
        except BackendError as e:
            errs[backend] = e
            log.warning("LLM backend '%s' failed: %s", backend, e)
    raise BackendError("All LLM backends failed (" +
                       "; ".join(f"{k}: {v}" for k, v in errs.items()) + ")")


def call_json(prompt, system=None, max_tokens=None, model=None):
    """Get a model completion and return parsed JSON (dict/list).

    `max_tokens` and `model` are accepted for call-site compatibility; the CLI
    manages its own token budget and the backend model is configured globally.

    Appends the strict-JSON instruction, then retries up to
    config.CLAUDE_MAX_RETRIES times on malformed output or backend errors.
    """
    full_prompt = f"{prompt.rstrip()}\n\n{_JSON_INSTRUCTION}"

    last_err = None
    for attempt in range(1, config.CLAUDE_MAX_RETRIES + 1):
        try:
            raw = _complete(full_prompt, system, max_tokens=max_tokens)
            return json.loads(_strip_to_json(raw))
        except json.JSONDecodeError as e:
            last_err = e
            log.warning("LLM JSON parse failed (attempt %d/%d): %s",
                        attempt, config.CLAUDE_MAX_RETRIES, e)
            full_prompt = (
                f"{prompt.rstrip()}\n\nYour previous response was not valid JSON. "
                f"{_JSON_INSTRUCTION}"
            )
        except BackendError as e:
            last_err = e
            log.warning("LLM backend error (attempt %d/%d): %s",
                        attempt, config.CLAUDE_MAX_RETRIES, e)

    raise ClaudeJSONError(
        f"Failed to get valid JSON after {config.CLAUDE_MAX_RETRIES} attempts: {last_err}"
    )
