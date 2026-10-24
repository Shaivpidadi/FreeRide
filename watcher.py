#!/usr/bin/env python3
"""
FreeRide Watcher

Background process that keeps the OpenClaw model chain healthy without ever
needing the agent to call out for help. Lives outside the inference loop, so
it can recover from a "every model in the chain is 429ing" deadlock that the
agent itself can't escape.

Default behavior: run as a daemon. Use --once for a single check, --status to
inspect state.
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from keyguard import redact
from main import (
    ConfigError,
    get_api_keys,
    get_current_model,
    load_openclaw_config,
    load_state as load_ownership_state,
    primary_is_managed,
    rotate,
    _test_model,
    _config_primary_to_api_id,
)


STATE_FILE = Path.home() / ".openclaw" / ".freeride-watcher-state.json"
DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 15

# The primary we last said we're leaving alone, so the daemon logs it once.
_skipped_primary = None


def _atomic_write(path: Path, content: str):
    """Write atomically via tmp + rename so a crash mid-write can't corrupt state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"rotation_count": 0}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"rotation_count": 0}


def save_state(state: dict):
    _atomic_write(STATE_FILE, json.dumps(state, indent=2))


def _record_rotation(state: dict, reason: str):
    state["rotation_count"] = state.get("rotation_count", 0) + 1
    state["last_rotation_at"] = datetime.now().isoformat()
    state["last_rotation_reason"] = reason
    save_state(state)


def check_and_rotate(state: dict) -> bool:
    """Probe current primary; rotate if it fails. Returns True if config was changed.

    Only a primary FreeRide set is probed. A user-configured primary is
    never tested (that could cost money) and never replaced.
    """
    global _skipped_primary
    try:
        config = load_openclaw_config()
    except ConfigError as e:
        print(f"[{datetime.now().isoformat()}] Not touching the config: {e}")
        return False
    current = get_current_model(config)

    if not current:
        print(f"[{datetime.now().isoformat()}] No primary configured — bootstrapping.")
        changed, err = rotate(force=True)
        if changed:
            _record_rotation(state, "bootstrap")
        elif err:
            print(f"  Bootstrap failed: {err}")
        return changed

    if not primary_is_managed(load_ownership_state(config), current):
        if _skipped_primary != current:
            print(f"[{datetime.now().isoformat()}] Primary {current} is user-configured, not touching it.")
            _skipped_primary = current
        return False
    _skipped_primary = None

    current_base = _config_primary_to_api_id(current)
    ok, err = _test_model(current_base)
    if ok:
        print(f"[{datetime.now().isoformat()}] {current_base} OK")
        return False

    print(f"[{datetime.now().isoformat()}] {current_base} failed ({err}) — rotating.")
    changed, rot_err = rotate(force=True)
    if changed:
        _record_rotation(state, err or "unknown")
    elif rot_err == "user_owned":
        pass
    elif rot_err:
        print(f"  Rotation failed: {rot_err}")
    return changed


def run_daemon(interval: int):
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)

    interval = max(interval, MIN_INTERVAL_SECONDS)
    key_count = len(get_api_keys())
    print(f"FreeRide Watcher started ({key_count} API key{'s' if key_count != 1 else ''}, interval {interval}s)")
    print("Stop with Ctrl-C or SIGTERM.")
    print("-" * 50)

    running = True

    def stop(signum, frame):
        nonlocal running
        print("\nShutting down watcher...")
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    state = load_state()
    while running:
        try:
            check_and_rotate(state)
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Watcher error: {redact(e)}")

        # Interruptible sleep so SIGTERM isn't held up by a long interval.
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    print("Watcher stopped.")


def run_once():
    if not get_api_keys():
        print("Error: OPENROUTER_API_KEY not set")
        sys.exit(1)
    state = load_state()
    try:
        check_and_rotate(state)
    except ConfigError as e:
        print(f"Error: {e}")
        sys.exit(2)


def show_status():
    state = load_state()
    print("FreeRide Watcher Status")
    print("=" * 40)
    print(f"State file: {STATE_FILE}")
    print(f"Total rotations: {state.get('rotation_count', 0)}")
    print(f"Last rotation: {state.get('last_rotation_at', 'never')}")
    print(f"Last reason: {state.get('last_rotation_reason', 'n/a')}")


def clear_state():
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"Cleared {STATE_FILE}")
    else:
        print("No state file to clear.")


def main():
    parser = argparse.ArgumentParser(
        prog="freeride-watcher",
        description="Background process that keeps the OpenClaw model chain healthy."
    )
    parser.add_argument("--interval", "-i", type=int, default=DEFAULT_INTERVAL_SECONDS,
                        help=f"Daemon check interval in seconds (default: {DEFAULT_INTERVAL_SECONDS}, min: {MIN_INTERVAL_SECONDS})")
    parser.add_argument("--once", action="store_true",
                        help="Run a single check-and-rotate, then exit")
    parser.add_argument("--status", "-s", action="store_true",
                        help="Show watcher state and exit")
    parser.add_argument("--clear", action="store_true",
                        help="Delete the watcher state file")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.clear:
        clear_state()
    elif args.once:
        run_once()
    else:
        run_daemon(args.interval)


if __name__ == "__main__":
    main()
