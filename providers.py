"""
Optional free-tier providers for FreeRide.

FreeRide only writes model refs into OpenClaw's config; OpenClaw talks to
each provider itself. So a provider here is just enough to:
  - discover its free, tool-capable model ids,
  - live-probe one of them with the user's own key,
  - and check that OpenClaw can already route the resulting
    `<provider>/<model>` ref (plugin loaded, ref in OpenClaw's catalog).

Nothing in this module writes files or keys. Every provider is opt-in;
OpenRouter stays the default and is handled in main.py.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import requests

from keyguard import redact


class Provider:
    def __init__(self, name, prefix, env_vars, base_url, plugin_package,
                 signup_url, models_path="/models", id_strip="",
                 trains_on_prompts=False, data_note=""):
        self.name = name
        self.prefix = prefix              # OpenClaw provider id / ref prefix
        self.env_vars = env_vars
        self.base_url = base_url
        self.models_url = base_url + models_path
        self.chat_url = base_url + "/chat/completions"
        self.plugin_package = plugin_package
        self.signup_url = signup_url
        self.id_strip = id_strip
        self.trains_on_prompts = trains_on_prompts
        self.data_note = data_note


# Groq ids that carry tool calling (from FreeRide v3's Groq model metadata),
# in preference order. Only these are ever written.
GROQ_TOOL_MODELS = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
)

# Cerebras /models lists ids that the inference API rejects.
CEREBRAS_KNOWN_BROKEN = frozenset({"zai-glm-4.7", "gpt-oss-120b"})

GEMINI_DATA_NOTE = (
    "Google may use prompts sent on the unpaid Gemini API tier to improve its "
    "products. EEA/UK/CH accounts are paid-only, and a project with prepaid "
    "billing answers 402 instead of serving the free tier."
)

PROVIDERS = {
    "groq": Provider(
        name="groq",
        prefix="groq",
        env_vars=("GROQ_API_KEY",),
        base_url="https://api.groq.com/openai/v1",
        plugin_package="@openclaw/groq-provider",
        signup_url="https://console.groq.com/keys",
    ),
    "gemini": Provider(
        name="gemini",
        prefix="google",
        env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        plugin_package="@openclaw/google-plugin",
        signup_url="https://aistudio.google.com/apikey",
        id_strip="models/",
        trains_on_prompts=True,
        data_note=GEMINI_DATA_NOTE,
    ),
    "cerebras": Provider(
        name="cerebras",
        prefix="cerebras",
        env_vars=("CEREBRAS_API_KEY",),
        base_url="https://api.cerebras.ai/v1",
        plugin_package="@openclaw/cerebras-provider",
        signup_url="https://cloud.cerebras.ai",
    ),
}

# Fallback order after OpenRouter: Groq second, Gemini third, Cerebras last.
PROVIDER_ORDER = ("groq", "gemini", "cerebras")
# Providers whose refs go at the very end of the fallback chain.
TAIL_PROVIDERS = ("cerebras",)

_OFF_WORDS = {"", "none", "off", "openrouter"}


def parse_provider_list(raw) -> list:
    """Parse `groq,gemini` (or a list) into known provider names, in
    PROVIDER_ORDER. `openrouter`, `none` and `off` mean OpenRouter only.
    Raises ValueError for anything unknown."""
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    names = set()
    for item in items:
        name = str(item).strip().lower()
        if name in _OFF_WORDS:
            continue
        if name == "google":
            name = "gemini"
        if name not in PROVIDERS:
            supported = ", ".join(PROVIDER_ORDER)
            raise ValueError(f"unknown or unsupported provider '{name}' (supported: {supported})")
        names.add(name)
    return [n for n in PROVIDER_ORDER if n in names]


# ============== Keys (read only) ==============

def read_dotenv(path: Path) -> dict:
    """Parse a simple KEY=VALUE .env file. Never written by FreeRide."""
    values = {}
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[name.strip()] = value
    return values


def resolve_secret(names, config: dict, dotenv_path: Path):
    """Find the first value for any of `names`, in the order OpenClaw reads
    provider keys: process env, ~/.openclaw/.env, `env.vars.<KEY>` in
    openclaw.json, then the legacy `env.<KEY>` shape. Returns the raw value
    (string or list) or None."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value

    dotenv = read_dotenv(dotenv_path)
    for name in names:
        if dotenv.get(name):
            return dotenv[name]

    env_block = config.get("env") if isinstance(config, dict) else None
    if isinstance(env_block, dict):
        env_vars = env_block.get("vars")
        if isinstance(env_vars, dict):
            for name in names:
                if env_vars.get(name):
                    return env_vars[name]
        for name in names:
            value = env_block.get(name)
            if isinstance(value, (str, list)) and value:
                return value
    return None


# ============== OpenClaw routing check ==============

def _run_openclaw(args: list):
    """Run the openclaw CLI read-only. Returns stdout, or None on any failure."""
    binary = shutil.which("openclaw")
    if not binary:
        return None
    try:
        proc = subprocess.run([binary] + args, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _parse_json_output(text):
    """openclaw may print a banner line before its JSON; start at the first brace."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        return None


def openclaw_routable_refs(provider: Provider):
    """Return the set of `<prefix>/<model>` refs OpenClaw can route for this
    provider, or (None, reason) when the plugin is missing or the CLI can't
    be queried. Returns (refs, None) on success."""
    plugins = _parse_json_output(_run_openclaw(["plugins", "list", "--json"]))
    if plugins is None:
        return None, "could not run `openclaw plugins list`"
    loaded = False
    for plugin in plugins.get("plugins", []) if isinstance(plugins, dict) else []:
        if provider.prefix not in (plugin.get("providerIds") or []):
            continue
        if plugin.get("enabled") is False:
            continue
        if str(plugin.get("status", "loaded")).lower() in ("error", "disabled", "failed"):
            continue
        loaded = True
        break
    if not loaded:
        return None, f"OpenClaw plugin {provider.plugin_package} is not installed or not enabled"

    catalog = _parse_json_output(
        _run_openclaw(["models", "list", "--all", "--provider", provider.prefix, "--json"]))
    if catalog is None:
        return None, f"could not read OpenClaw's {provider.prefix} model catalog"
    refs = {m.get("key") for m in catalog.get("models", []) if isinstance(m, dict) and m.get("key")}
    if not refs:
        return None, f"OpenClaw lists no {provider.prefix} models"
    return refs, None


# ============== Discovery ==============

def gemini_is_free(model_id: str) -> bool:
    """Flash / Flash-Lite and Gemma only. No Pro, no retired 1.x/2.x ids,
    no embedding, image, tts or live models."""
    mid = model_id[len("models/"):] if model_id.startswith("models/") else model_id
    if not (mid.startswith("gemini-") or mid.startswith("gemma-")):
        return False
    if mid.startswith("gemini-1.") or mid.startswith("gemini-2."):
        return False
    for word in ("pro", "embedding", "image", "tts", "live"):
        if word in mid:
            return False
    if mid.startswith("gemma-"):
        return True
    return "flash" in mid


def _gemini_rank(model_id: str):
    # Full Flash before Flash-Lite before Gemma; stable releases before previews.
    return ("gemma" in model_id, "lite" in model_id, "preview" in model_id)


def free_tool_candidates(provider: Provider, live_ids: list) -> list:
    """Filter a provider's live model ids to free, tool-capable candidates,
    best first."""
    ids = []
    for raw_id in live_ids:
        mid = raw_id
        if provider.id_strip and mid.startswith(provider.id_strip):
            mid = mid[len(provider.id_strip):]
        if mid and mid not in ids:
            ids.append(mid)

    if provider.name == "groq":
        return [m for m in GROQ_TOOL_MODELS if m in ids]
    if provider.name == "gemini":
        return sorted([m for m in ids if gemini_is_free(m)], key=_gemini_rank)
    if provider.name == "cerebras":
        return [m for m in ids if m not in CEREBRAS_KNOWN_BROKEN]
    return []


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def list_live_models(provider: Provider, keys: list):
    """Fetch the provider's /models ids. Returns (ids, error)."""
    last_err = "no key"
    for key in keys:
        try:
            response = requests.get(provider.models_url, headers=_headers(key), timeout=30)
        except requests.RequestException as e:
            last_err = f"network error ({redact(e)})"
            continue
        if response.status_code == 200:
            try:
                data = response.json().get("data", []) or []
            except ValueError:
                return [], "unreadable /models response"
            return [m.get("id", "") for m in data if isinstance(m, dict)], None
        last_err = f"HTTP {response.status_code}"
    return [], last_err


_TOOL_PROBE = {
    "messages": [{"role": "user", "content": "Call the ping tool."}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Health check. Takes no arguments.",
            "parameters": {"type": "object", "properties": {}},
        },
    }],
    "tool_choice": "required",
    "max_tokens": 64,
    "stream": False,
}


def probe_tool_call(provider: Provider, model_id: str, keys: list):
    """One small chat call that must come back with a tool call.
    Returns (ok, error)."""
    payload = dict(_TOOL_PROBE, model=model_id)
    last_err = "no key"
    for key in keys:
        try:
            response = requests.post(provider.chat_url, headers=_headers(key), json=payload, timeout=30)
        except requests.Timeout:
            return False, "timeout"
        except requests.RequestException:
            return False, "request_error"
        if response.status_code in (401, 403, 429):
            last_err = f"error_{response.status_code}"
            continue
        if response.status_code != 200:
            return False, f"error_{response.status_code}"
        try:
            message = response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            return False, "bad_response"
        if message.get("tool_calls"):
            return True, None
        return False, "no_tool_call"
    return False, last_err


def pick_model(provider: Provider, keys: list, log=print):
    """Choose one routable, free, tool-capable model for `provider`.
    Returns an OpenClaw ref like `groq/openai/gpt-oss-120b`, or None."""
    if not keys:
        log(f"  {provider.name}: skipped, {provider.env_vars[0]} is not set "
            f"(add it to ~/.openclaw/.env; get one at {provider.signup_url})")
        return None

    routable, reason = openclaw_routable_refs(provider)
    if routable is None:
        log(f"  {provider.name}: skipped, {reason}.")
        log(f"    Install it yourself with: openclaw plugins install {provider.plugin_package}")
        return None

    live_ids, err = list_live_models(provider, keys)
    if err:
        log(f"  {provider.name}: skipped, could not list models ({err}).")
        return None

    for model_id in free_tool_candidates(provider, live_ids):
        ref = f"{provider.prefix}/{model_id}"
        if ref not in routable:
            continue
        ok, probe_err = probe_tool_call(provider, model_id, keys)
        if ok:
            log(f"  {provider.name}: {ref} (tool call verified)")
            return ref
        if probe_err in ("error_401", "error_403", "error_429"):
            log(f"  {provider.name}: skipped, key rejected or rate-limited ({probe_err}).")
            return None
    log(f"  {provider.name}: skipped, no free tool-capable model passed the check.")
    return None
