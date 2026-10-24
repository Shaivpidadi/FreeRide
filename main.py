#!/usr/bin/env python3
"""
FreeRide - Free AI for OpenClaw
Automatically manage and switch between free AI models on OpenRouter
for unlimited free AI access.
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

import providers as provider_mod
from keyguard import mask_key, redact


# Constants
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
CACHE_FILE = Path.home() / ".openclaw" / ".freeride-cache.json"
CACHE_DURATION_HOURS = 6
# Which primary/fallbacks FreeRide set, and what was there before.
STATE_FILE = Path.home() / ".openclaw" / ".freeride-state.json"
# Copy of openclaw.json taken before every FreeRide write.
BACKUP_FILE = Path.home() / ".openclaw" / "openclaw.json.freeride-bak"
# OpenClaw's recommended place for provider keys. FreeRide only reads it.
DOTENV_PATH = Path.home() / ".openclaw" / ".env"

# OpenRouter app-attribution headers — applied to every request so all
# FreeRide traffic shows up under one identity on OpenRouter's App Activity
# page. https://openrouter.ai/docs/api-reference/overview#headers
OPENROUTER_REFERER = "https://github.com/Shaivpidadi/FreeRide"
OPENROUTER_APP_TITLE = "FreeRide Health Check"


def _openrouter_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_REFERER,
        "X-Title": OPENROUTER_APP_TITLE,
    }

# Per-process tracking of keys that recently returned 429/401, with a soft
# cooldown so keys come back into rotation automatically. Short-lived CLI runs
# never reach the cooldown; the watcher daemon does.
_KEY_COOLDOWN_SECONDS = 120
_RATE_LIMITED_KEYS: dict = {}  # key -> timestamp when marked


def _is_key_in_cooldown(key: str) -> bool:
    ts = _RATE_LIMITED_KEYS.get(key)
    if ts is None:
        return False
    if time.time() - ts > _KEY_COOLDOWN_SECONDS:
        _RATE_LIMITED_KEYS.pop(key, None)
        return False
    return True


def _mark_key_rate_limited(key: str):
    _RATE_LIMITED_KEYS[key] = time.time()

# Free model ranking criteria (higher is better)
RANKING_WEIGHTS = {
    "context_length": 0.4,      # Prefer longer context
    "capabilities": 0.3,        # Prefer more capabilities
    "recency": 0.2,            # Prefer newer models
    "provider_trust": 0.1       # Prefer trusted providers
}

# Trusted providers (in order of preference)
TRUSTED_PROVIDERS = [
    "google", "meta-llama", "mistralai", "deepseek",
    "nvidia", "qwen", "microsoft", "allenai", "arcee-ai"
]


def _parse_api_keys(raw) -> list:
    """Parse a single key string, a JSON array literal, or a real list of keys."""
    if isinstance(raw, list):
        return [k.strip() for k in raw if isinstance(k, str) and k.strip()]
    if not isinstance(raw, str):
        return []
    raw = raw.strip()
    if raw.startswith("["):
        try:
            keys = json.loads(raw)
            if isinstance(keys, list):
                return [k.strip() for k in keys if isinstance(k, str) and k.strip()]
        except (json.JSONDecodeError, ValueError):
            pass
    return [raw] if raw else []


def _read_config_quietly() -> dict:
    """Best-effort config read for key lookup only. Never raises."""
    try:
        config = json.loads(OPENCLAW_CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def _resolve_keys(env_names) -> list:
    raw = provider_mod.resolve_secret(env_names, _read_config_quietly(), DOTENV_PATH)
    return _parse_api_keys(raw) if raw else []


def get_api_keys() -> list:
    """Get all OpenRouter API keys. Accepts a single key or a JSON array.

    Single key:  OPENROUTER_API_KEY=sk-or-v1-...
    Multiple:    OPENROUTER_API_KEY=["sk-or-v1-key1","sk-or-v1-key2"]

    Looked up in the environment, then ~/.openclaw/.env, then `env.vars` and
    the legacy `env` block of openclaw.json. FreeRide never writes keys.
    """
    return _resolve_keys(("OPENROUTER_API_KEY",))


def get_provider_keys(name: str) -> list:
    """Keys for an optional provider (groq, gemini, cerebras)."""
    return _resolve_keys(provider_mod.PROVIDERS[name].env_vars)


def get_api_key() -> Optional[str]:
    """Get the first available OpenRouter API key."""
    keys = get_api_keys()
    return keys[0] if keys else None


def fetch_all_models() -> list:
    """Fetch all models from OpenRouter, rotating through API keys on 429/401."""
    keys = get_api_keys()
    if not keys:
        return []

    last_status = None
    for i, key in enumerate(keys, 1):
        if _is_key_in_cooldown(key):
            continue
        try:
            response = requests.get(OPENROUTER_API_URL, headers=_openrouter_headers(key), timeout=30)
        except requests.RequestException as e:
            print(f"  Key {i}: network error ({redact(e)})")
            continue

        if response.status_code == 200:
            return response.json().get("data", [])
        if response.status_code in (401, 429):
            label = "invalid" if response.status_code == 401 else "rate-limited"
            print(f"  Key {i}: {label}, trying next...")
            _mark_key_rate_limited(key)
            last_status = response.status_code
            continue
        print(f"Error fetching models: HTTP {response.status_code}")
        return []

    if last_status:
        print(f"Error: all API keys exhausted (last status: {last_status}).")
    else:
        print("Error: no usable API keys.")
    return []


def _is_chat_model(model: dict) -> bool:
    """True if the model produces text-only output, i.e. is suitable for
    /chat/completions. Filters out image-gen, audio-gen, and multi-modal output
    models (e.g. Lyria's `text+image->text+audio`) that aren't chat-shaped.
    """
    arch = model.get("architecture") or {}

    # Preferred: explicit output_modalities array
    out_mods = arch.get("output_modalities")
    if isinstance(out_mods, list) and out_mods:
        return out_mods == ["text"]

    # Fallback: parse modality string like "text+image->text" or "text->text+audio"
    modality = arch.get("modality", "")
    if isinstance(modality, str) and "->" in modality:
        output_part = modality.split("->", 1)[1].strip()
        return output_part == "text"

    # Unknown shape — keep it; rotate's live probe will catch false positives.
    return True


def filter_free_models(models: list) -> list:
    """Filter models to free, text-output (chat-shaped) models only."""
    free_models = []
    seen_ids = set()

    for model in models:
        model_id = model.get("id", "")
        if model_id in seen_ids:
            continue
        if not _is_chat_model(model):
            continue

        is_free = False
        pricing = model.get("pricing") or {}
        prompt_cost = pricing.get("prompt")
        if prompt_cost is not None:
            try:
                # A model is only free if output is free too.
                is_free = float(prompt_cost) == 0 and float(pricing.get("completion") or 0) == 0
            except (ValueError, TypeError):
                pass
        if not is_free and ":free" in model_id:
            is_free = True

        if is_free:
            free_models.append(model)
            seen_ids.add(model_id)

    return free_models


def calculate_model_score(model: dict) -> float:
    """Calculate a ranking score for a model based on multiple criteria."""
    score = 0.0

    # Context length score (normalized to 0-1, max 1M tokens)
    context_length = model.get("context_length", 0)
    context_score = min(context_length / 1_000_000, 1.0)
    score += context_score * RANKING_WEIGHTS["context_length"]

    # Capabilities score
    capabilities = model.get("supported_parameters", [])
    capability_count = len(capabilities) if capabilities else 0
    capability_score = min(capability_count / 10, 1.0)  # Normalize to max 10 capabilities
    score += capability_score * RANKING_WEIGHTS["capabilities"]

    # Recency score (based on creation date)
    created = model.get("created", 0)
    if created:
        days_old = (time.time() - created) / 86400
        recency_score = max(0, 1 - (days_old / 365))  # Newer models score higher
        score += recency_score * RANKING_WEIGHTS["recency"]

    # Provider trust score
    model_id = model.get("id", "")
    provider = model_id.split("/")[0] if "/" in model_id else ""
    if provider in TRUSTED_PROVIDERS:
        trust_index = TRUSTED_PROVIDERS.index(provider)
        trust_score = 1 - (trust_index / len(TRUSTED_PROVIDERS))
        score += trust_score * RANKING_WEIGHTS["provider_trust"]

    return score


def rank_free_models(models: list) -> list:
    """Rank free models by quality score."""
    scored_models = []
    for model in models:
        score = calculate_model_score(model)
        scored_models.append({**model, "_score": score})

    # Sort by score descending
    scored_models.sort(key=lambda x: x["_score"], reverse=True)
    return scored_models


def get_cached_models() -> Optional[list]:
    """Get cached model list if still valid."""
    if not CACHE_FILE.exists():
        return None

    try:
        cache = json.loads(CACHE_FILE.read_text())
        cached_at = datetime.fromisoformat(cache.get("cached_at", ""))
        if datetime.now() - cached_at < timedelta(hours=CACHE_DURATION_HOURS):
            return cache.get("models", [])
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def save_models_cache(models: list):
    """Save models to cache file."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cache = {
        "cached_at": datetime.now().isoformat(),
        "models": models
    }
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def get_free_models(force_refresh: bool = False) -> list:
    """Get ranked free models (from cache or API)."""
    if not force_refresh:
        cached = get_cached_models()
        if cached:
            return cached

    all_models = fetch_all_models()
    free_models = filter_free_models(all_models)
    ranked_models = rank_free_models(free_models)

    if ranked_models:
        save_models_cache(ranked_models)
    return ranked_models


class ConfigError(Exception):
    """openclaw.json can't be safely read or rewritten. Nothing was written."""


class UsageError(Exception):
    """Bad command-line or environment input. Nothing was written."""


def load_openclaw_config() -> dict:
    """Load OpenClaw configuration.

    Raises ConfigError if the file exists but isn't plain JSON. OpenClaw
    accepts JSON5 (comments, trailing commas); FreeRide can't round-trip
    that, and treating it as empty would wipe the file on the next save.
    """
    if not OPENCLAW_CONFIG_PATH.exists():
        return {}

    try:
        text = OPENCLAW_CONFIG_PATH.read_text()
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Could not read {OPENCLAW_CONFIG_PATH}: {redact(e)}")
    if not text.strip():
        return {}
    try:
        config = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"{OPENCLAW_CONFIG_PATH} is not plain JSON "
            f"({e.msg} at line {e.lineno}, column {e.colno}).\n"
            "OpenClaw allows JSON5 (comments, trailing commas), but FreeRide only "
            "rewrites files it can parse exactly, so it will not touch this one.\n"
            "Nothing was written. To use FreeRide, remove the comments and trailing "
            "commas from the file, then run the command again."
        )
    if not isinstance(config, dict):
        raise ConfigError(f"{OPENCLAW_CONFIG_PATH} does not contain a JSON object. Nothing was written.")
    return config


def _ensure_writable(config: dict):
    """Refuse configs FreeRide can't safely rewrite as a single file."""
    if "$include" in config:
        raise ConfigError(
            f"{OPENCLAW_CONFIG_PATH} uses $include. FreeRide edits only this one file "
            "and could shadow settings from the included files, so it will not write it.\n"
            "Nothing was written. Set the model with `openclaw config set` instead."
        )


def _atomic_write(path: Path, content: str, mode: Optional[int] = None):
    """Write via a temporary sibling + os.replace so a crash can't leave a
    half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".freeride-tmp")
    try:
        with open(tmp, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def save_openclaw_config(config: dict):
    """Save OpenClaw configuration: back up the current file, then write atomically."""
    _ensure_writable(config)
    mode = 0o600
    if OPENCLAW_CONFIG_PATH.exists():
        mode = OPENCLAW_CONFIG_PATH.stat().st_mode & 0o777
        shutil.copy2(OPENCLAW_CONFIG_PATH, BACKUP_FILE)
    _atomic_write(OPENCLAW_CONFIG_PATH, json.dumps(config, indent=2), mode)


# ============== Ownership state ==============
#
# FreeRide only rotates a primary it set itself. The state file records
# what FreeRide wrote and what was there before, so `freeride restore`
# can put it back.

STATE_SCHEMA = 1
SMART_ROUTER_REF = "openrouter/openrouter/free"


def _empty_state() -> dict:
    return {
        "schema": STATE_SCHEMA,
        "primary_owner": None,      # "freeride", "user", or None (no primary)
        "managed_primary": None,    # last primary FreeRide wrote
        "managed_fallbacks": [],    # fallback entries FreeRide owns
        "added_model_keys": [],     # agents.defaults.models keys FreeRide added
        "providers": [],            # opted-in providers beyond OpenRouter
        "allow_training": [],       # providers the user consented to despite prompt training
        "previous": None,           # {"primary", "fallbacks", "saved_at"}
    }


def _looks_freeride_ref(ref) -> bool:
    """A ref FreeRide would write itself: an OpenRouter free model or the
    openrouter/free smart router."""
    return isinstance(ref, str) and ref.startswith("openrouter/") and (
        ref.endswith(":free") or ref == SMART_ROUTER_REF)


def _infer_state(config: dict) -> dict:
    """Build state for installs that predate the state file."""
    state = _empty_state()
    primary = get_current_model(config)
    fallbacks = list(get_current_fallbacks(config) or [])
    state["managed_fallbacks"] = [f for f in fallbacks if _looks_freeride_ref(f)]
    if not primary:
        return state
    if _looks_freeride_ref(primary):
        state["primary_owner"] = "freeride"
        state["managed_primary"] = primary
    else:
        state["primary_owner"] = "user"
        state["previous"] = {
            "primary": primary,
            "fallbacks": [f for f in fallbacks if f not in state["managed_fallbacks"]],
            "saved_at": datetime.now().isoformat(),
        }
    return state


def _read_state_file() -> Optional[dict]:
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    state = _empty_state()
    state.update(data)
    return state


def load_state(config: dict) -> dict:
    """Ownership state, inferred from the config the first time."""
    state = _read_state_file()
    return state if state is not None else _infer_state(config)


def save_state(state: dict):
    _atomic_write(STATE_FILE, json.dumps(state, indent=2))


def primary_is_managed(state: dict, primary) -> bool:
    """True only for a primary FreeRide set and still owns."""
    return bool(primary) and state.get("primary_owner") == "freeride" \
        and state.get("managed_primary") == primary


def _snapshot_previous(state: dict, config: dict):
    """Save the current primary and the user's own fallbacks before a change.
    A value FreeRide wrote never replaces the user's saved original."""
    primary = get_current_model(config)
    if state.get("previous") is not None and (not primary or primary == state.get("managed_primary")):
        return
    managed = state.get("managed_fallbacks") or []
    state["previous"] = {
        "primary": primary,
        "fallbacks": [f for f in (get_current_fallbacks(config) or []) if f not in managed],
        "saved_at": datetime.now().isoformat(),
    }


def _allow_model(config: dict, state: dict, ref: str):
    """Add `ref` to the agents.defaults.models allowlist, keeping any
    settings the user already has for it."""
    models = config["agents"]["defaults"]["models"]
    if ref not in models:
        models[ref] = {}
        if ref not in state["added_model_keys"]:
            state["added_model_keys"].append(ref)


def _set_managed_primary(config: dict, state: dict, ref: str):
    config["agents"]["defaults"]["model"]["primary"] = ref
    _allow_model(config, state, ref)
    state["primary_owner"] = "freeride"
    state["managed_primary"] = ref


def _set_fallbacks(config: dict, state: dict, managed_new: list):
    """Write FreeRide's fallbacks, keeping the user's own entries first."""
    primary = get_current_model(config)
    old_managed = state.get("managed_fallbacks") or []
    user_entries = [f for f in (get_current_fallbacks(config) or [])
                    if f not in old_managed and f != primary]
    # FreeRide's own list is kept exactly as built (1.0 output is unchanged);
    # only the user's entries are deduplicated against it.
    merged = [f for f in user_entries if f not in managed_new] + list(managed_new)
    for ref in managed_new:
        _allow_model(config, state, ref)
    state["managed_fallbacks"] = [f for f in managed_new if f not in user_entries]
    config["agents"]["defaults"]["model"]["fallbacks"] = merged


def _commit(config: dict, state: dict):
    save_openclaw_config(config)
    save_state(state)


# ============== Optional providers ==============

def resolve_providers(state: dict, flag_value=None, allow_training_flag: bool = False) -> list:
    """Work out which extra providers are enabled for this run.

    `--providers` wins and is remembered in the state file; otherwise
    FREERIDE_PROVIDERS; otherwise what was remembered. With none of these,
    the result is [] and FreeRide behaves as OpenRouter-only.
    Raises ValueError on an unknown provider name.
    """
    try:
        if flag_value is not None:
            names = provider_mod.parse_provider_list(flag_value)
        elif os.environ.get("FREERIDE_PROVIDERS") is not None:
            names = provider_mod.parse_provider_list(os.environ["FREERIDE_PROVIDERS"])
        else:
            names = provider_mod.parse_provider_list(state.get("providers") or [])
        env_consent = provider_mod.parse_provider_list(os.environ.get("FREERIDE_ALLOW_TRAINING") or [])
    except ValueError as e:
        raise UsageError(str(e))

    consented = set(state.get("allow_training") or [])
    consented.update(env_consent)
    if allow_training_flag:
        consented.update(n for n in names if provider_mod.PROVIDERS[n].trains_on_prompts)

    enabled = []
    for name in names:
        provider = provider_mod.PROVIDERS[name]
        if provider.trains_on_prompts and name not in consented:
            print(f"Note: {name} needs explicit consent. {provider.data_note}")
            print("  Add --allow-training-providers (or FREERIDE_ALLOW_TRAINING="
                  f"{name}) to enable it. Skipping {name}.")
            continue
        if provider.trains_on_prompts and allow_training_flag:
            print(f"Note: {provider.data_note}")
        enabled.append(name)

    if flag_value is not None:
        state["providers"] = list(enabled)
        state["allow_training"] = [n for n in enabled if provider_mod.PROVIDERS[n].trains_on_prompts]
    return enabled


def _validate_provider_args(args):
    """Fail fast on a bad --providers value, before any network call."""
    try:
        provider_mod.parse_provider_list(getattr(args, "providers", None))
    except ValueError as e:
        raise UsageError(str(e))


def _pick_provider_refs(names: list) -> dict:
    """name -> OpenClaw ref for each enabled provider that passes its checks."""
    picked = {}
    if not names:
        return picked
    print("Checking optional providers...")
    for name in names:
        ref = provider_mod.pick_model(provider_mod.PROVIDERS[name], get_provider_keys(name))
        if ref:
            picked[name] = ref
    return picked


def _weave_provider_refs(base: list, picked: dict, total: int) -> list:
    """Place provider refs into an OpenRouter fallback list: openrouter/free,
    then Groq, Gemini, then OpenRouter free models, with Cerebras last.
    The list keeps `total` entries; OpenRouter fills whatever is left."""
    if not picked:
        return base
    router = [SMART_ROUTER_REF] if base and base[0] == SMART_ROUTER_REF else []
    rest = base[len(router):]
    head = router + [picked[n] for n in provider_mod.PROVIDER_ORDER
                     if n in picked and n not in provider_mod.TAIL_PROVIDERS]
    tail = [picked[n] for n in provider_mod.TAIL_PROVIDERS if n in picked]
    room = max(0, total - len(head) - len(tail))
    return (head + rest[:room] + tail)[:total]


def format_model_for_openclaw(model_id: str, append_free: bool = True) -> str:
    """Format an OpenRouter model ID for OpenClaw config.

    OpenClaw routes by first segment: it parses the leading `<provider>/`,
    sets that as the provider, and forwards the rest verbatim to the
    provider's API. So *every* config value gets a leading `openrouter/`
    routing prefix — even for OpenRouter-native models, which means a
    literal `openrouter/openrouter/free` lands in config. After OpenClaw
    strips the leading provider, OpenRouter receives the bare `openrouter/free`
    model ID it actually expects.

    Examples:
      qwen/qwen3-coder:free   → openrouter/qwen/qwen3-coder:free
      qwen/qwen3-coder        → openrouter/qwen/qwen3-coder:free  (append_free=True)
      openrouter/free         → openrouter/openrouter/free
      openrouter/owl-alpha    → openrouter/openrouter/owl-alpha

    OpenRouter-native models (those whose API ID already starts with
    `openrouter/`) don't take the `:free` tier suffix.
    """
    is_native = model_id.startswith("openrouter/")
    base_id = model_id
    if append_free and not is_native and ":free" not in base_id:
        base_id = f"{base_id}:free"
    return f"openrouter/{base_id}"


def _config_primary_to_api_id(stored_id: str) -> str:
    """Recover the OpenRouter API model ID by stripping OpenClaw's leading
    `openrouter/` provider prefix. Inverse of `format_model_for_openclaw`.

      openrouter/qwen/qwen3-coder:free  → qwen/qwen3-coder:free
      openrouter/openrouter/free        → openrouter/free
      openrouter/openrouter/owl-alpha   → openrouter/owl-alpha
    """
    prefix = "openrouter/"
    return stored_id[len(prefix):] if stored_id.startswith(prefix) else stored_id


def get_current_model(config: dict = None) -> Optional[str]:
    """Get currently configured model in OpenClaw."""
    if config is None:
        config = load_openclaw_config()
    return config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")


def get_current_fallbacks(config: dict = None) -> list:
    """Get currently configured fallback models."""
    if config is None:
        config = load_openclaw_config()
    return config.get("agents", {}).get("defaults", {}).get("model", {}).get("fallbacks", [])


def ensure_config_structure(config: dict) -> dict:
    """Ensure the config has the required nested structure without overwriting existing values."""
    if "agents" not in config:
        config["agents"] = {}
    if "defaults" not in config["agents"]:
        config["agents"]["defaults"] = {}
    if "model" not in config["agents"]["defaults"]:
        config["agents"]["defaults"]["model"] = {}
    if "models" not in config["agents"]["defaults"]:
        config["agents"]["defaults"]["models"] = {}
    return config


AUTH_PROFILE_ID = "openrouter:default"
AUTH_PROFILE_VALUE = {"provider": "openrouter", "mode": "api_key"}


def confirm_setup_auth(config: dict, assume_yes: bool) -> bool:
    """Explain exactly what --setup-auth writes and get consent first.
    Returns False if the user declined or no consent could be asked for."""
    profiles = (config.get("auth") or {}).get("profiles") or {}
    if AUTH_PROFILE_ID in profiles:
        print(f"Auth profile {AUTH_PROFILE_ID} already exists; --setup-auth will not change it.")
        return True
    print(f"--setup-auth will add one entry to {OPENCLAW_CONFIG_PATH}:")
    print(f'  auth.profiles["{AUTH_PROFILE_ID}"] = {json.dumps(AUTH_PROFILE_VALUE)}')
    print("It tells OpenClaw to authenticate OpenRouter with your OPENROUTER_API_KEY.")
    print("No API key is written, and auth-profiles.json is not touched.")
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Not running in a terminal, so FreeRide can't ask. Re-run with --yes to confirm.")
        print("Nothing was written.")
        return False
    try:
        answer = input("Add this entry? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer in ("y", "yes"):
        return True
    print("Cancelled. Nothing was written.")
    return False


def setup_openrouter_auth(config: dict) -> dict:
    """Set up OpenRouter auth profile if not exists."""
    if "auth" not in config:
        config["auth"] = {}
    if "profiles" not in config["auth"]:
        config["auth"]["profiles"] = {}

    if AUTH_PROFILE_ID not in config["auth"]["profiles"]:
        config["auth"]["profiles"][AUTH_PROFILE_ID] = dict(AUTH_PROFILE_VALUE)
        print("Added OpenRouter auth profile.")

    return config


def update_model_config(
    model_id: str,
    as_primary: bool = True,
    add_fallbacks: bool = True,
    fallback_count: int = 5,
    setup_auth: bool = False,
    append_free: bool = True,
    providers_flag: Optional[str] = None,
    allow_training: bool = False,
    pin_user_primary: bool = False,
) -> bool:
    """Update OpenClaw config with the specified model.

    Args:
        model_id: The model ID to configure
        as_primary: If True, set as primary model. If False, only add to fallbacks.
        add_fallbacks: If True, also configure fallback models
        fallback_count: Number of fallback models to add
        setup_auth: If True, also set up OpenRouter auth profile
        providers_flag: `--providers` value; None means env or saved choice
        allow_training: `--allow-training-providers` was given
        pin_user_primary: Mark the current primary as the user's, so FreeRide
            never rotates it (used by `-f`)
    """
    config = load_openclaw_config()
    _ensure_writable(config)
    state = load_state(config)
    config = ensure_config_structure(config)
    _snapshot_previous(state, config)

    extra = resolve_providers(state, providers_flag, allow_training)

    if setup_auth:
        config = setup_openrouter_auth(config)

    formatted = format_model_for_openclaw(model_id, append_free=append_free)

    if as_primary:
        _set_managed_primary(config, state, formatted)
    elif pin_user_primary and get_current_model(config):
        state["primary_owner"] = "user"

    if add_fallbacks and get_api_keys():
        free_models = get_free_models()
        new_fallbacks = []

        # openrouter/free smart router is always the first fallback unless the
        # user is making it the primary.
        smart_router = format_model_for_openclaw("openrouter/free")
        if formatted != smart_router:
            new_fallbacks.append(smart_router)

        for m in free_models:
            if len(new_fallbacks) >= fallback_count:
                break

            m_formatted = format_model_for_openclaw(m["id"])

            if "openrouter/free" in m["id"]:
                continue
            if as_primary and m_formatted == formatted:
                continue
            current_primary = config["agents"]["defaults"]["model"].get("primary", "")
            if not as_primary and m_formatted == current_primary:
                continue

            new_fallbacks.append(m_formatted)

        if not as_primary:
            if formatted not in new_fallbacks:
                insert_pos = 1 if smart_router in new_fallbacks else 0
                new_fallbacks.insert(insert_pos, formatted)

        picked = _pick_provider_refs(extra)
        new_fallbacks = _weave_provider_refs(new_fallbacks, picked, max(fallback_count, len(new_fallbacks)))
        _set_fallbacks(config, state, new_fallbacks)

    _commit(config, state)
    return True


# ============== Command Handlers ==============

def cmd_list(args):
    """List available free models ranked by quality."""
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        print("Add OPENROUTER_API_KEY=<your key> to ~/.openclaw/.env in your editor,")
        print("or export it in your shell. Get a free key at: https://openrouter.ai/keys")
        sys.exit(1)

    print("Fetching free models from OpenRouter...")
    models = get_free_models(force_refresh=args.refresh)

    if not models:
        print("No free models available.")
        return

    current = get_current_model()
    fallbacks = get_current_fallbacks()
    limit = args.limit if args.limit else 15

    print(f"\nTop {min(limit, len(models))} Free AI Models (ranked by quality):\n")
    print(f"{'#':<3} {'Model ID':<50} {'Context':<12} {'Score':<8} {'Status'}")
    print("-" * 90)

    for i, model in enumerate(models[:limit], 1):
        model_id = model.get("id", "unknown")
        context = model.get("context_length", 0)
        score = model.get("_score", 0)

        # Format context length
        if context >= 1_000_000:
            context_str = f"{context // 1_000_000}M tokens"
        elif context >= 1_000:
            context_str = f"{context // 1_000}K tokens"
        else:
            context_str = f"{context} tokens"

        formatted = format_model_for_openclaw(model_id)

        if current and formatted == current:
            status = "[PRIMARY]"
        elif formatted in fallbacks:
            status = "[FALLBACK]"
        else:
            status = ""

        print(f"{i:<3} {model_id:<50} {context_str:<12} {score:.3f}    {status}")

    if len(models) > limit:
        print(f"\n... and {len(models) - limit} more. Use --limit to see more.")

    print(f"\nTotal free models available: {len(models)}")
    print("\nCommands:")
    print("  freeride switch <model>      Set as primary model")
    print("  freeride switch <model> -f   Add to fallbacks only (keep current primary)")
    print("  freeride auto                Auto-select best model")


def cmd_switch(args):
    """Switch to a specific free model."""
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)

    model_id = args.model
    as_fallback = args.fallback_only

    config = load_openclaw_config()
    _ensure_writable(config)
    if args.setup_auth and not confirm_setup_auth(config, args.yes):
        sys.exit(1)
    _validate_provider_args(args)

    # Validate model exists and is free
    models = get_free_models()
    model_ids = [m["id"] for m in models]

    # Check for exact match or partial match
    matched_model = None
    if model_id in model_ids:
        matched_model = model_id
    else:
        # Try partial match
        for m_id in model_ids:
            if model_id.lower() in m_id.lower():
                matched_model = m_id
                break

    if not matched_model:
        print(f"Error: Model '{model_id}' not found in free models list.")
        print("Use 'freeride list' to see available models.")
        sys.exit(1)

    if as_fallback:
        print(f"Adding to fallbacks: {matched_model}")
    else:
        print(f"Setting as primary: {matched_model}")

    if update_model_config(
        matched_model,
        as_primary=not as_fallback,
        add_fallbacks=not args.no_fallbacks,
        setup_auth=args.setup_auth,
        append_free=False,
        providers_flag=args.providers,
        allow_training=args.allow_training_providers,
        pin_user_primary=as_fallback,
    ):
        config = load_openclaw_config()

        if as_fallback:
            print("Success! Added to fallbacks.")
            print(f"Primary model (unchanged): {get_current_model(config)}")
        else:
            print("Success! OpenClaw config updated.")
            print(f"Primary model: {get_current_model(config)}")

        fallbacks = get_current_fallbacks(config)
        if fallbacks:
            print(f"Fallback models ({len(fallbacks)}):")
            for fb in fallbacks[:5]:
                print(f"  - {fb}")
            if len(fallbacks) > 5:
                print(f"  ... and {len(fallbacks) - 5} more")

        print("\nRestart OpenClaw for changes to take effect.")
    else:
        print("Error: Failed to update OpenClaw config.")
        sys.exit(1)


def cmd_auto(args):
    """Automatically select the best free model."""
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)

    config = load_openclaw_config()
    _ensure_writable(config)
    current_primary = get_current_model(config)
    if args.setup_auth and not confirm_setup_auth(config, args.yes):
        sys.exit(1)
    _validate_provider_args(args)

    print("Finding best free model...")
    models = get_free_models(force_refresh=True)

    if not models:
        print("Error: No free models available.")
        sys.exit(1)

    # Find best SPECIFIC model (skip openrouter/free router)
    # openrouter/free is a router, not a specific model - use it as fallback only
    best_model = None
    for m in models:
        if "openrouter/free" not in m["id"]:
            best_model = m
            break

    if not best_model:
        # Fallback to first model if all are routers (unlikely)
        best_model = models[0]

    model_id = best_model["id"]
    context = best_model.get("context_length", 0)
    score = best_model.get("_score", 0)

    # Determine if we should change primary or just add fallbacks
    as_fallback = args.fallback_only

    if not as_fallback:
        if current_primary:
            print(f"\nReplacing current primary: {current_primary}")
            if not primary_is_managed(load_state(config), current_primary):
                print("  (saved first; `freeride restore` puts it back)")
        print(f"\nBest free model: {model_id}")
        print(f"Context length: {context:,} tokens")
        print(f"Quality score: {score:.3f}")
    else:
        print(f"\nKeeping current primary, adding fallbacks only.")
        print(f"Best available: {model_id} ({context:,} tokens, score: {score:.3f})")

    if update_model_config(
        model_id,
        as_primary=not as_fallback,
        add_fallbacks=True,
        fallback_count=args.fallback_count,
        setup_auth=args.setup_auth,
        providers_flag=args.providers,
        allow_training=args.allow_training_providers,
        pin_user_primary=as_fallback,
    ):
        config = load_openclaw_config()

        if as_fallback:
            print("\nFallbacks configured!")
            print(f"Primary (unchanged): {get_current_model(config)}")
            if get_current_model(config):
                print("  Marked as yours: FreeRide and freeride-watcher will not change it.")
            print("First fallback: openrouter/free (smart router - auto-selects best available)")
        else:
            print("\nOpenClaw config updated!")
            print(f"Primary: {get_current_model(config)}")

        fallbacks = get_current_fallbacks(config)
        if fallbacks:
            print(f"Fallbacks ({len(fallbacks)}):")
            for fb in fallbacks:
                print(f"  - {fb}")

        print("\nRestart OpenClaw for changes to take effect.")
    else:
        print("Error: Failed to update config.")
        sys.exit(1)


def cmd_status(args):
    """Show current configuration status."""
    keys = get_api_keys()
    config = load_openclaw_config()
    current = get_current_model(config)
    fallbacks = get_current_fallbacks(config)

    print("FreeRide Status")
    print("=" * 50)

    # API Key status
    if keys:
        if len(keys) == 1:
            print(f"OpenRouter API Key: {mask_key(keys[0])}")
        else:
            print(f"OpenRouter API Keys: {len(keys)} configured")
            for i, k in enumerate(keys, 1):
                print(f"  {i}. {mask_key(k)}")
    else:
        print("OpenRouter API Key: NOT SET")
        print("  Add OPENROUTER_API_KEY=<your key> to ~/.openclaw/.env, or export it.")
        print('  Multiple keys: OPENROUTER_API_KEY=["key1","key2"]')

    # Auth profile status
    auth_profiles = config.get("auth", {}).get("profiles", {})
    if "openrouter:default" in auth_profiles:
        print("OpenRouter Auth Profile: Configured")
    else:
        print("OpenRouter Auth Profile: Not set (use --setup-auth to add)")

    # Current model
    state = load_state(config)
    print(f"\nPrimary Model: {current or 'Not configured'}")
    if current:
        if primary_is_managed(state, current):
            print("  Set by FreeRide (rotates when it fails)")
        else:
            print("  Yours (FreeRide will not change it)")

    # Fallbacks
    if fallbacks:
        print(f"Fallback Models ({len(fallbacks)}):")
        for fb in fallbacks:
            print(f"  - {fb}")
    else:
        print("Fallback Models: None configured")

    # Optional providers
    enabled = state.get("providers") or []
    print(f"\nExtra providers: {', '.join(enabled) if enabled else 'none (OpenRouter only)'}")
    for name in provider_mod.PROVIDER_ORDER:
        have = "set" if get_provider_keys(name) else "missing"
        print(f"  {name}: key {have}")

    prev = state.get("previous") if STATE_FILE.exists() else None
    if prev is not None:
        print(f"\nSaved for restore: primary {prev.get('primary') or '(none)'}, "
              f"{len(prev.get('fallbacks') or [])} fallback(s) "
              "(run `freeride restore --dry-run` to preview)")

    # Cache status
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text())
            cached_at = datetime.fromisoformat(cache.get("cached_at", ""))
            models_count = len(cache.get("models", []))
            age = datetime.now() - cached_at
            hours = age.seconds // 3600
            mins = (age.seconds % 3600) // 60
            print(f"\nModel Cache: {models_count} models (updated {hours}h {mins}m ago)")
        except (json.JSONDecodeError, ValueError, KeyError):
            print("\nModel Cache: Invalid")
    else:
        print("\nModel Cache: Not created yet")

    # OpenClaw config path
    print(f"\nOpenClaw Config: {OPENCLAW_CONFIG_PATH}")
    print(f"  Exists: {'Yes' if OPENCLAW_CONFIG_PATH.exists() else 'No'}")


def cmd_refresh(args):
    """Force refresh the model cache."""
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)

    print("Refreshing free models cache...")
    models = get_free_models(force_refresh=True)
    print(f"Cached {len(models)} free models.")
    print(f"Cache expires in {CACHE_DURATION_HOURS} hours.")


def cmd_fallbacks(args):
    """Configure fallback models for rate limit handling."""
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)

    _validate_provider_args(args)
    config = load_openclaw_config()
    _ensure_writable(config)
    state = load_state(config)
    current = get_current_model(config)

    if not current:
        print("Warning: No primary model configured.")
        print("Fallbacks will still be added.")

    print(f"Current primary: {current or 'None'}")
    print(f"Setting up {args.count} fallback models...")

    extra = resolve_providers(state, args.providers, args.allow_training_providers)
    models = get_free_models()
    config = ensure_config_structure(config)
    _snapshot_previous(state, config)

    fallbacks = []

    # openrouter/free smart router always leads.
    smart_router = format_model_for_openclaw("openrouter/free")
    if not current or current != smart_router:
        fallbacks.append(smart_router)

    for m in models:
        formatted = format_model_for_openclaw(m["id"])

        if current and formatted == current:
            continue
        if "openrouter/free" in m["id"]:
            continue
        if len(fallbacks) >= args.count:
            break

        fallbacks.append(formatted)

    fallbacks = _weave_provider_refs(fallbacks, _pick_provider_refs(extra), args.count)
    _set_fallbacks(config, state, fallbacks)
    _commit(config, state)
    fallbacks = get_current_fallbacks(config)

    print(f"\nConfigured {len(fallbacks)} fallback models:")
    for i, fb in enumerate(fallbacks, 1):
        print(f"  {i}. {fb}")

    print("\nWhen rate limited, OpenClaw will automatically try these models.")
    print("Restart OpenClaw for changes to take effect.")


def _test_model(model_id: str):
    """Probe a model with a tiny chat call. Rotates through API keys on 429/401.

    Returns (success: bool, error: Optional[str]). Error codes:
      "all_keys_exhausted", "model_not_found", "unavailable", "timeout",
      "request_error", "error_<status>".
    """
    available = [k for k in get_api_keys() if not _is_key_in_cooldown(k)]
    if not available:
        return False, "all_keys_exhausted"

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,
        "stream": False
    }

    for key in available:
        try:
            response = requests.post(OPENROUTER_CHAT_URL, headers=_openrouter_headers(key), json=payload, timeout=30)
        except requests.Timeout:
            return False, "timeout"
        except requests.RequestException:
            return False, "request_error"

        if response.status_code == 200:
            return True, None
        if response.status_code in (401, 429):
            _mark_key_rate_limited(key)
            continue  # try next key — this one is dead for now
        if response.status_code == 503:
            return False, "unavailable"

        # OpenRouter returns model_not_found in the body on 4xx — check the body
        # regardless of status code.
        try:
            body = response.json()
            err_code = body.get("error", {}).get("code", "")
            err_msg = str(body.get("error", {}).get("message", ""))
            if err_code == "model_not_found" or "Unknown model" in err_msg:
                return False, "model_not_found"
        except (ValueError, KeyError):
            pass
        return False, f"error_{response.status_code}"

    return False, "all_keys_exhausted"


def rotate(force: bool = False, fallback_count: int = 5,
           providers_flag: Optional[str] = None, allow_training: bool = False):
    """Live-test current primary; swap to a verified working model if it fails.

    Only touches a primary FreeRide set itself (or bootstraps one when there
    is none). A primary the user configured is never probed or replaced.

    Tests every candidate via /chat/completions before writing it to config, so
    no stale model IDs end up in the fallback chain. Tries multiple API keys.

    Returns (changed: bool, error: Optional[str]). `changed` is True when the
    config was rewritten; `error` is set when nothing could be done.
    """
    if not get_api_keys():
        return False, "no_keys"

    config = load_openclaw_config()
    _ensure_writable(config)
    state = load_state(config)
    config = ensure_config_structure(config)
    current = get_current_model(config)

    if current and not primary_is_managed(state, current):
        return False, "user_owned"

    current_base = _config_primary_to_api_id(current) if current else None

    if current_base and not force:
        print(f"Testing current primary: {current_base}")
        ok, err = _test_model(current_base)
        if ok:
            print("  Status: OK — no rotation needed.")
            return False, None
        print(f"  Status: {err}")

    extra = resolve_providers(state, providers_flag, allow_training)

    print("Finding a working free model...")
    models = get_free_models(force_refresh=True)
    if not models:
        return False, "fetch_failed"

    # openrouter/free is always fallback #0, so we need (count - 1) verified extras.
    fallback_target = max(0, fallback_count - 1)
    new_primary = None
    verified_fallbacks = []

    for m in models:
        model_id = m["id"]
        if "openrouter/free" in model_id:
            continue
        if model_id == current_base:
            continue

        ok, err = _test_model(model_id)
        if ok:
            if new_primary is None:
                new_primary = model_id
                print(f"  Verified primary: {model_id}")
            else:
                verified_fallbacks.append(model_id)
                print(f"  Verified fallback: {model_id}")
            if len(verified_fallbacks) >= fallback_target:
                break
        elif err == "all_keys_exhausted":
            print("  Stopped: all API keys are rate-limited or invalid.")
            break
        # Silent on per-model failures (model_not_found, etc.) — try next.

    if not new_primary:
        return False, "no_working_models"

    _snapshot_previous(state, config)
    formatted = format_model_for_openclaw(new_primary)
    _set_managed_primary(config, state, formatted)

    smart_router = format_model_for_openclaw("openrouter/free")
    fallbacks = [smart_router] + [format_model_for_openclaw(fb_id) for fb_id in verified_fallbacks]
    fallbacks = _weave_provider_refs(fallbacks, _pick_provider_refs(extra), fallback_count)
    _set_fallbacks(config, state, fallbacks)
    _commit(config, state)

    fallbacks = get_current_fallbacks(config)
    print(f"Done. Primary: {formatted}")
    print(f"Fallbacks ({len(fallbacks)}):")
    for fb in fallbacks:
        print(f"  - {fb}")
    return True, None


def cmd_rotate(args):
    """CLI wrapper around rotate()."""
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)

    _validate_provider_args(args)
    changed, err = rotate(force=args.force, fallback_count=args.fallback_count,
                          providers_flag=args.providers,
                          allow_training=args.allow_training_providers)
    if err == "user_owned":
        print(f"Primary {get_current_model()} was not set by FreeRide (or was kept with -f),")
        print("so FreeRide will not test or replace it.")
        print("To hand the primary to FreeRide, run `freeride auto` (your current one is saved first).")
        sys.exit(1)
    if err == "fetch_failed":
        print("Error: could not fetch free model list (all keys exhausted?).")
        sys.exit(1)
    if err == "no_working_models":
        print("Error: no working free models found.")
        sys.exit(1)
    if changed:
        print("\nRestart OpenClaw for changes to take effect.")
    elif not err:
        print("  (Use --force to rotate anyway.)")


def cmd_restore(args):
    """Put back the primary and fallbacks that were there before FreeRide."""
    state = _read_state_file()
    prev = state.get("previous") if state else None
    if prev is None:
        print("Nothing to restore: FreeRide has no saved primary or fallbacks.")
        return

    config = load_openclaw_config()
    _ensure_writable(config)
    config = ensure_config_structure(config)
    model = config["agents"]["defaults"]["model"]
    models = config["agents"]["defaults"]["models"]

    primary = prev.get("primary")
    fallbacks = list(prev.get("fallbacks") or [])
    keep = {primary} | set(fallbacks)
    drop_keys = [k for k in state.get("added_model_keys") or [] if k in models and k not in keep]

    print(f"Primary:   {model.get('primary') or '(none)'}  ->  {primary or '(none)'}")
    print(f"Fallbacks: {len(model.get('fallbacks') or [])} entries  ->  {len(fallbacks)} entries")
    for fb in fallbacks:
        print(f"  - {fb}")
    if drop_keys:
        print(f"Removing {len(drop_keys)} model allowlist entries FreeRide added.")

    if args.dry_run:
        print("\nDry run: nothing was written.")
        return

    if primary:
        model["primary"] = primary
    else:
        model.pop("primary", None)
    if fallbacks:
        model["fallbacks"] = fallbacks
    else:
        model.pop("fallbacks", None)
    for k in drop_keys:
        models.pop(k, None)

    state["primary_owner"] = "user" if primary else None
    state["managed_primary"] = None
    state["managed_fallbacks"] = []
    state["added_model_keys"] = []
    state["previous"] = None
    _commit(config, state)

    print(f"\nRestored. Backup of the previous file: {BACKUP_FILE}")
    if not primary:
        print("Note: a running freeride-watcher sets a new primary when none is configured.")
    print("Restart OpenClaw for changes to take effect.")


def _add_provider_args(p):
    p.add_argument("--providers", metavar="LIST", default=None,
                   help="Opt in to extra free providers after OpenRouter: groq, gemini, cerebras "
                        "(comma-separated; remembered). 'openrouter' turns them off again.")
    p.add_argument("--allow-training-providers", action="store_true",
                   help="Consent to providers whose free tier may use prompts for training (gemini)")


def main():
    parser = argparse.ArgumentParser(
        prog="freeride",
        description="FreeRide - Free AI for OpenClaw. Manage free models from OpenRouter."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list command
    list_parser = subparsers.add_parser("list", help="List available free models")
    list_parser.add_argument("--limit", "-n", type=int, default=15,
                            help="Number of models to show (default: 15)")
    list_parser.add_argument("--refresh", "-r", action="store_true",
                            help="Force refresh from API (ignore cache)")

    # switch command
    switch_parser = subparsers.add_parser("switch", help="Switch to a specific model")
    switch_parser.add_argument("model", help="Model ID to switch to")
    switch_parser.add_argument("--fallback-only", "-f", action="store_true",
                              help="Add to fallbacks only, don't change primary (marks it as yours)")
    switch_parser.add_argument("--no-fallbacks", action="store_true",
                              help="Don't configure fallback models")
    switch_parser.add_argument("--setup-auth", action="store_true",
                              help="Also add the auth.profiles[\"openrouter:default\"] entry (asks first)")
    switch_parser.add_argument("--yes", "-y", action="store_true",
                              help="Confirm --setup-auth without asking")
    _add_provider_args(switch_parser)

    # auto command
    auto_parser = subparsers.add_parser("auto", help="Auto-select best free model")
    auto_parser.add_argument("--fallback-count", "-c", type=int, default=5,
                            help="Number of fallback models (default: 5)")
    auto_parser.add_argument("--fallback-only", "-f", action="store_true",
                            help="Add to fallbacks only, don't change primary (marks it as yours)")
    auto_parser.add_argument("--setup-auth", action="store_true",
                            help="Also add the auth.profiles[\"openrouter:default\"] entry (asks first)")
    auto_parser.add_argument("--yes", "-y", action="store_true",
                            help="Confirm --setup-auth without asking")
    _add_provider_args(auto_parser)

    # status command
    subparsers.add_parser("status", help="Show current configuration")

    # refresh command
    subparsers.add_parser("refresh", help="Refresh model cache")

    # fallbacks command
    fallbacks_parser = subparsers.add_parser("fallbacks", help="Configure fallback models")
    fallbacks_parser.add_argument("--count", "-c", type=int, default=5,
                                 help="Number of fallback models (default: 5)")
    _add_provider_args(fallbacks_parser)

    # rotate command
    rotate_parser = subparsers.add_parser("rotate",
        help="Live-test current primary; swap to a working model if it fails")
    rotate_parser.add_argument("--force", "-f", action="store_true",
                              help="Rotate even if the current primary is healthy")
    rotate_parser.add_argument("--fallback-count", "-c", type=int, default=5,
                              help="Total fallback slots including openrouter/free (default: 5)")
    _add_provider_args(rotate_parser)

    # restore command
    restore_parser = subparsers.add_parser("restore",
        help="Put back the primary and fallbacks from before FreeRide changed them")
    restore_parser.add_argument("--dry-run", action="store_true",
                               help="Show what would change without writing")

    args = parser.parse_args()

    handlers = {
        "list": cmd_list,
        "switch": cmd_switch,
        "auto": cmd_auto,
        "status": cmd_status,
        "refresh": cmd_refresh,
        "fallbacks": cmd_fallbacks,
        "rotate": cmd_rotate,
        "restore": cmd_restore,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    try:
        handler(args)
    except (ConfigError, UsageError) as e:
        print(f"Error: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
