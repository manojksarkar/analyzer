"""Build HTTP headers for the corporate OpenAI-compatible gateway.

The gateway requires several non-standard headers (x-dep-ticket, User-Type,
User-Id, Send-System-Name) plus a fresh UUID per request for Prompt-Msg-Id /
Completion-Msg-Id. Values come from environment variables first, then
config['llmServer']['customHeaders'], then defaults.
"""

import os
import uuid
from typing import Dict, Optional


# Default values used when neither env var nor config provides one.
_DEFAULTS = {
    "x-dep-ticket": "credential:",
    "User-Type": "AD_ID",
    "User-Id": "",
    "Send-System-Name": "rvc-api-module",
}

# Environment variable names that override the defaults.
_ENV_VARS = {
    "x-dep-ticket": "X_DEP_TICKET",
    "User-Type": "USER_TYPE",
    "User-Id": "USER_ID",
    "Send-System-Name": "SEND_SYSTEM_NAME",
}


def _resolve(name: str, config_headers: Dict[str, str]) -> str:
    """Resolve a single custom header value.

    Order: env var > config['llmServer']['customHeaders'][name] > built-in default.
    """
    env_name = _ENV_VARS.get(name)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    if name in config_headers:
        return str(config_headers[name])
    return _DEFAULTS.get(name, "")


def build_openai_headers(
    api_key: Optional[str] = None,
    config_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build the full header dict for one OpenAI-compatible POST.

    Generates fresh Prompt-Msg-Id / Completion-Msg-Id UUIDs every call.
    Includes Authorization only if api_key is provided.
    """
    cfg = config_headers or {}
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prompt-Msg-Id": str(uuid.uuid4()),
        "Completion-Msg-Id": str(uuid.uuid4()),
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for name in _DEFAULTS:
        headers[name] = _resolve(name, cfg)
    # Allow config to inject extra headers we don't know about.
    for k, v in cfg.items():
        if k not in headers:
            headers[k] = str(v)
    return headers


#: The Claude Messages API's version header (`anthropic-version`).
ANTHROPIC_VERSION = "2023-06-01"


def build_anthropic_headers(
    api_key: Optional[str] = None,
    config_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """The headers of one Claude Messages API request: the key as `x-api-key`, the API's version,
    and `customHeaders` as they are -- a proxy in front of the API may want its own. None of the
    corporate gateway's defaults (x-dep-ticket, User-Id, ...): that gateway is the openai
    provider's."""
    headers: Dict[str, str] = {
        "content-type": "application/json",
        "accept": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    if api_key:
        headers["x-api-key"] = api_key
    for k, v in (config_headers or {}).items():
        headers[str(k)] = str(v)
    return headers


def resolve_api_key(config_llm: Dict) -> Optional[str]:
    """Resolve API key. Env var LLM_API_KEY takes precedence over config."""
    env = os.environ.get("LLM_API_KEY")
    if env:
        return env
    key = (config_llm or {}).get("apiKey")
    return str(key) if key else None
