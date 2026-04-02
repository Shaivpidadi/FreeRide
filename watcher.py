#!/usr/bin/env python3
"""
FreeRide Watcher
Monitors for rate limits and automatically rotates models.
Can run as a daemon or be called periodically via cron.
"""

import json
import os
import sys
import time
import signal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

try:
    import requests
except ImportError:
    print("Error: requests library required")
    sys.exit(1)


# Import from main module
from main import (
    get_api_keys,
    get_free_models,
    load_openclaw_config,
    save_openclaw_config,
    ensure_config_structure,
    format_model_for_openclaw,
    OPENCLAW_CONFIG_PATH
)


# Constants
STATE_FILE = Path.home() / ".openclaw" / ".freeride-watcher-state.json"
RATE_LIMIT_COOLDOWN_MINUTES = 30
KEY_RATE_LIMIT_COOLDOWN_MINUTES = 2  # Per-minute key limits reset quickly
DEAD_MODEL_TTL_HOURS = 24            # Retry dead models after 24h (OpenRouter sometimes brings them back)
CHECK_INTERVAL_SECONDS = 60
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_state() -> dict:
    """Load watcher state."""
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            state.setdefault("rate_limited_keys", {})
            state.setdefault("dead_models", {})
            state.setdefault("invalid_keys", [])
            return state
        except json.JSONDecodeError:
            pass
    return {"rate_limited_models": {}, "rate_limited_keys": {}, "dead_models": {}, "invalid_keys": [], "rotation_count": 0}


def save_state(state: dict):
    """Save watcher state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def is_model_rate_limited(state: dict, model_id: str) -> bool:
    """Check if a model is currently in rate-limit cooldown."""
    rate_limited = state.get("rate_limited_models", {})
    if model_id not in rate_limited:
        return False

    limited_at = datetime.fromisoformat(rate_limited[model_id])
    cooldown_end = limited_at + timedelta(minutes=RATE_LIMIT_COOLDOWN_MINUTES)
    return datetime.now() < cooldown_end


def mark_rate_limited(state: dict, model_id: str):
    """Mark a model as rate limited."""
    if "rate_limited_models" not in state:
        state["rate_limited_models"] = {}
    state["rate_limited_models"][model_id] = datetime.now().isoformat()
    save_state(state)


def is_key_rate_limited(state: dict, key: str) -> bool:
    """Check if an API key is in rate-limit cooldown."""
    key_id = key[-8:]
    rate_limited = state.get("rate_limited_keys", {})
    if key_id not in rate_limited:
        return False
    limited_at = datetime.fromisoformat(rate_limited[key_id])
    return datetime.now() < limited_at + timedelta(minutes=KEY_RATE_LIMIT_COOLDOWN_MINUTES)


def mark_key_rate_limited(state: dict, key: str):
    """Mark an API key as rate limited."""
    key_id = key[-8:]
    if "rate_limited_keys" not in state:
        state["rate_limited_keys"] = {}
    state["rate_limited_keys"][key_id] = datetime.now().isoformat()
    save_state(state)


def is_key_invalid(state: dict, key: str) -> bool:
    """Check if a key was permanently rejected with 401."""
    return key[-8:] in state.get("invalid_keys", [])


def mark_key_invalid(state: dict, key: str):
    """Mark a key as invalid (401). Skipped until --clear-cooldowns is run."""
    key_id = key[-8:]
    if "invalid_keys" not in state:
        state["invalid_keys"] = []
    if key_id not in state["invalid_keys"]:
        state["invalid_keys"].append(key_id)
        save_state(state)
        print(f"  WARNING: Key ...{key_id} returned 401 — invalid or revoked. Skipping.")


def is_model_dead(state: dict, model_id: str) -> bool:
    """Check if a model was previously confirmed as model_not_found."""
    dead = state.get("dead_models", {})
    if model_id not in dead:
        return False
    marked_at = datetime.fromisoformat(dead[model_id])
    return datetime.now() < marked_at + timedelta(hours=DEAD_MODEL_TTL_HOURS)


def mark_model_dead(state: dict, model_id: str):
    """Mark a model as permanently gone (model_not_found)."""
    if "dead_models" not in state:
        state["dead_models"] = {}
    state["dead_models"][model_id] = datetime.now().isoformat()
    save_state(state)
    print(f"  Marked dead (model_not_found): {model_id}")


def get_available_key(state: dict) -> Optional[str]:
    """Return the first API key that is not rate-limited or invalid."""
    for key in get_api_keys():
        if not is_key_rate_limited(state, key) and not is_key_invalid(state, key):
            return key
    return None


def test_model_with_keys(state: dict, model_id: str) -> tuple[bool, Optional[str]]:
    """
    Test model availability, rotating through API keys on 429.
    Returns (success, error).
    """
    keys = get_api_keys()
    last_error = "no_keys"

    for key in keys:
        if is_key_rate_limited(state, key) or is_key_invalid(state, key):
            continue
        success, error = test_model(key, model_id)
        if success:
            return True, None
        if error == "rate_limit":
            masked = key[:8] + "..." + key[-4:]
            print(f"  Key {masked} rate limited, trying next...")
            mark_key_rate_limited(state, key)
            last_error = error
            continue
        if error == "invalid_key":
            mark_key_invalid(state, key)
            last_error = error
            continue  # try next key — this one is bad
        last_error = error
        break  # model-level error (not_found, 503, etc.), no point trying more keys

    return False, last_error


def test_model(api_key: str, model_id: str) -> tuple[bool, Optional[str]]:
    """
    Test if a model is available by making a minimal API call.
    Returns (success, error_type).
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Shaivpidadi/FreeRide",
        "X-Title": "FreeRide Health Check"
    }

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,
        "stream": False
    }

    try:
        response = requests.post(
            OPENROUTER_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code == 200:
            return True, None
        elif response.status_code == 401:
            return False, "invalid_key"
        elif response.status_code == 429:
            return False, "rate_limit"
        elif response.status_code == 503:
            return False, "unavailable"
        else:
            # OpenRouter returns model_not_found as a JSON error code — can appear
            # on 400, 404, or other 4xx. Check the body regardless of status.
            try:
                body = response.json()
                err_code = body.get("error", {}).get("code", "")
                err_msg = str(body.get("error", {}).get("message", ""))
                if err_code == "model_not_found" or "Unknown model" in err_msg:
                    return False, "model_not_found"
            except Exception:
                pass
            return False, f"error_{response.status_code}"

    except requests.Timeout:
        return False, "timeout"
    except requests.RequestException as e:
        return False, "request_error"


def get_next_available_model(state: dict, exclude_model: str = None) -> Optional[str]:
    """Get the next best model that isn't rate limited."""
    api_key = get_available_key(state)
    if not api_key:
        return None

    models = get_free_models(api_key)

    for model in models:
        model_id = model["id"]

        if "openrouter/free" in model_id:
            continue
        if exclude_model and model_id == exclude_model:
            continue
        if is_model_rate_limited(state, model_id) or is_model_dead(state, model_id):
            continue

        success, error = test_model_with_keys(state, model_id)
        if success:
            return model_id
        if error == "rate_limit":
            mark_rate_limited(state, model_id)
        elif error == "model_not_found":
            mark_model_dead(state, model_id)

    return None


def rotate_to_next_model(state: dict, reason: str = "manual", force_refresh: bool = False):
    """Rotate to the next available model.

    Tests candidates live before writing to config — no stale model IDs end up
    in the fallbacks list. Finds primary + fallbacks in a single pass.
    """
    api_key = get_available_key(state)
    if not api_key:
        print("  Error: All API keys are rate limited!")
        return False

    config = load_openclaw_config()
    config = ensure_config_structure(config)
    current = config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")

    current_base = None
    if current:
        if current.startswith("openrouter/"):
            current_base = current[len("openrouter/"):]
        else:
            current_base = current

    print(f"[{datetime.now().isoformat()}] Rotating from: {current_base or 'none'}")
    print(f"  Reason: {reason}")

    models = get_free_models(api_key, force_refresh=force_refresh)

    # Single pass: find up to 6 live models (1 primary + 5 fallbacks).
    # Each candidate is tested before being written — no stale IDs in config.
    working = []
    for model in models:
        if len(working) >= 6:
            break
        model_id = model["id"]
        if "openrouter/free" in model_id or model_id == current_base:
            continue
        if is_model_dead(state, model_id) or is_model_rate_limited(state, model_id):
            continue

        success, error = test_model_with_keys(state, model_id)
        if success:
            working.append(model_id)
        elif error == "model_not_found":
            mark_model_dead(state, model_id)
        elif error == "rate_limit":
            mark_rate_limited(state, model_id)
        elif error in ("invalid_key", "no_keys"):
            break  # no usable keys left, stop testing models

    if not working:
        print("  Error: No available models found!")
        return False

    new_primary = working[0]
    print(f"  New model: {new_primary}")

    formatted_primary = format_model_for_openclaw(new_primary, with_provider_prefix=True)
    config["agents"]["defaults"]["model"]["primary"] = formatted_primary
    config["agents"]["defaults"]["models"][format_model_for_openclaw(new_primary, with_provider_prefix=False)] = {}

    # openrouter/free smart router always leads fallbacks, then verified models
    fallbacks = ["openrouter/free"]
    config["agents"]["defaults"]["models"]["openrouter/free"] = {}
    for m_id in working[1:]:
        fb = format_model_for_openclaw(m_id, with_provider_prefix=False)
        fallbacks.append(fb)
        config["agents"]["defaults"]["models"][fb] = {}

    config["agents"]["defaults"]["model"]["fallbacks"] = fallbacks
    save_openclaw_config(config)

    state["rotation_count"] = state.get("rotation_count", 0) + 1
    state["last_rotation"] = datetime.now().isoformat()
    state["last_rotation_reason"] = reason
    save_state(state)

    print(f"  Success! Rotated to {new_primary}")
    print(f"  Verified fallbacks: {len(fallbacks) - 1} model(s) + openrouter/free")
    print(f"  Total rotations this session: {state['rotation_count']}")

    return True


def check_and_rotate(state: dict) -> bool:
    """Check current model and rotate if needed."""
    config = load_openclaw_config()
    current = config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")

    if not current:
        print("No primary model configured. Running initial setup...")
        return rotate_to_next_model(state, "initial_setup")

    if current.startswith("openrouter/"):
        current_base = current[len("openrouter/"):]
    else:
        current_base = current

    if is_model_rate_limited(state, current_base):
        return rotate_to_next_model(state, "cooldown_active")

    print(f"[{datetime.now().isoformat()}] Testing: {current_base}")
    success, error = test_model_with_keys(state, current_base)

    if success:
        print(f"  Status: OK")
        return False
    else:
        print(f"  Status: {error}")
        if error == "rate_limit":
            mark_rate_limited(state, current_base)
            return rotate_to_next_model(state, error)
        elif error == "model_not_found":
            # Model was removed from OpenRouter — cache is likely stale too
            mark_model_dead(state, current_base)
            return rotate_to_next_model(state, error, force_refresh=True)
        else:
            return rotate_to_next_model(state, error)


def cleanup_old_rate_limits(state: dict):
    """Remove expired rate limit entries for both models and keys."""
    current_time = datetime.now()

    # Clean model cooldowns
    rate_limited = state.get("rate_limited_models", {})
    expired_models = [
        m for m, t in rate_limited.items()
        if current_time - datetime.fromisoformat(t) > timedelta(minutes=RATE_LIMIT_COOLDOWN_MINUTES)
    ]
    for m in expired_models:
        del rate_limited[m]
        print(f"  Cleared model cooldown: {m}")

    # Clean key cooldowns
    rate_limited_keys = state.get("rate_limited_keys", {})
    expired_keys = [
        k for k, t in rate_limited_keys.items()
        if current_time - datetime.fromisoformat(t) > timedelta(minutes=KEY_RATE_LIMIT_COOLDOWN_MINUTES)
    ]
    for k in expired_keys:
        del rate_limited_keys[k]
        print(f"  Cleared key cooldown: ...{k}")

    # Expire dead model entries after TTL (OpenRouter occasionally restores models)
    dead_models = state.get("dead_models", {})
    expired_dead = [
        m for m, t in dead_models.items()
        if current_time - datetime.fromisoformat(t) > timedelta(hours=DEAD_MODEL_TTL_HOURS)
    ]
    for m in expired_dead:
        del dead_models[m]

    if expired_models or expired_keys or expired_dead:
        save_state(state)


def run_once():
    """Run a single check and rotate cycle."""
    from main import get_api_keys
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)

    state = load_state()
    cleanup_old_rate_limits(state)
    check_and_rotate(state)


def run_daemon():
    """Run as a continuous daemon."""
    from main import get_api_keys
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)

    key_count = len(get_api_keys())
    print(f"FreeRide Watcher started ({key_count} API key{'s' if key_count > 1 else ''})")
    print(f"Check interval: {CHECK_INTERVAL_SECONDS}s")
    print(f"Model cooldown: {RATE_LIMIT_COOLDOWN_MINUTES}m | Key cooldown: {KEY_RATE_LIMIT_COOLDOWN_MINUTES}m")
    print("-" * 50)

    running = True
    def signal_handler(signum, frame):
        nonlocal running
        print("\nShutting down watcher...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    state = load_state()

    while running:
        try:
            cleanup_old_rate_limits(state)
            check_and_rotate(state)
        except Exception as e:
            print(f"Error during check: {e}")

        for _ in range(CHECK_INTERVAL_SECONDS):
            if not running:
                break
            time.sleep(1)

    print("Watcher stopped.")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="freeride-watcher",
        description="FreeRide Watcher - Monitor and auto-rotate free AI models"
    )
    parser.add_argument("--daemon", "-d", action="store_true",
                       help="Run as continuous daemon")
    parser.add_argument("--rotate", "-r", action="store_true",
                       help="Force rotate to next model")
    parser.add_argument("--status", "-s", action="store_true",
                       help="Show watcher status")
    parser.add_argument("--clear-cooldowns", action="store_true",
                       help="Clear all rate limit cooldowns")

    args = parser.parse_args()

    if args.status:
        state = load_state()
        print("FreeRide Watcher Status")
        print("=" * 40)
        print(f"Total rotations: {state.get('rotation_count', 0)}")
        print(f"Last rotation: {state.get('last_rotation', 'Never')}")
        print(f"Last reason: {state.get('last_rotation_reason', 'N/A')}")
        print(f"\nModels in cooldown:")
        for model, limited_at in state.get("rate_limited_models", {}).items():
            print(f"  - {model} (since {limited_at})")
        if not state.get("rate_limited_models"):
            print("  None")
        print(f"\nAPI keys in cooldown:")
        for key_id, limited_at in state.get("rate_limited_keys", {}).items():
            print(f"  - ...{key_id} (since {limited_at})")
        if not state.get("rate_limited_keys"):
            print("  None")
        print(f"\nInvalid API keys (401):")
        for key_id in state.get("invalid_keys", []):
            print(f"  - ...{key_id}")
        if not state.get("invalid_keys"):
            print("  None")
        print(f"\nDead models (model_not_found):")
        for model, marked_at in state.get("dead_models", {}).items():
            print(f"  - {model} (since {marked_at})")
        if not state.get("dead_models"):
            print("  None")

    elif args.clear_cooldowns:
        state = load_state()
        state["rate_limited_models"] = {}
        state["rate_limited_keys"] = {}
        state["dead_models"] = {}
        state["invalid_keys"] = []
        save_state(state)
        print("Cleared all model cooldowns, key cooldowns, dead models, and invalid keys.")

    elif args.rotate:
        if not get_api_keys():
            print("Error: OPENROUTER_API_KEY not set")
            sys.exit(1)
        state = load_state()
        rotate_to_next_model(state, "manual_rotation")

    elif args.daemon:
        run_daemon()

    else:
        run_once()


if __name__ == "__main__":
    main()