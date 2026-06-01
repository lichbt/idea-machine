"""LLM wrapper that enforces valid-JSON responses with retries.

Backend order: the Claude CLI (`claude -p`) is tried first; if it is not
installed or errors, we fall back to the OpenRouter API. JSON-parsing retries
sit on top of whichever backend produced the text.

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
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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


def _complete_via_openrouter(prompt, system, model):
    """Completion via OpenRouter chat API. Returns text or raises BackendError."""
    if not config.OPENROUTER_API_KEY:
        raise BackendError("OPENROUTER_API_KEY unset; cannot use fallback")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = requests.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": model or config.OPENROUTER_MODEL, "messages": messages},
            timeout=config.CLAUDE_CLI_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        raise BackendError(f"OpenRouter request failed: {e}")


def _complete(prompt, system):
    """Get raw text, preferring the Claude CLI, falling back to OpenRouter."""
    cli_err = None
    if _cli_present():
        try:
            return _complete_via_cli(prompt, system, config.CLAUDE_CLI_MODEL)
        except BackendError as e:
            cli_err = e
            log.warning("Claude CLI failed, falling back to OpenRouter: %s", e)
    try:
        return _complete_via_openrouter(prompt, system, config.OPENROUTER_MODEL)
    except BackendError as e:
        raise BackendError(
            f"All LLM backends failed (cli: {cli_err}; openrouter: {e})"
        )


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
            raw = _complete(full_prompt, system)
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
