"""Who owns the primary, saving the previous one, and `freeride restore`."""

import main
import watcher
from conftest import (
    BEST, OR_CHAT_URL, ROUTER, FakeResponse, config_with, read_config, read_state, ref, run_cli,
    write_config,
)

PAID_OR = "openrouter/anthropic/claude-x"
PAID_DIRECT = "anthropic/claude-x"
USER_FB = "openai/gpt-x"


# ---------- watcher and rotate never touch a user's primary ----------

def test_watcher_preserves_paid_primary(home, net, or_key):
    write_config(home, config_with(primary=PAID_OR, fallbacks=[ROUTER]))
    net.post_routes[OR_CHAT_URL] = lambda payload: FakeResponse(402, {"error": {"code": 402}})

    changed = watcher.check_and_rotate({"rotation_count": 0})

    assert changed is False
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == PAID_OR
    assert net.calls == []  # not even a probe: probing a paid model costs money


def test_watcher_preserves_non_openrouter_primary(home, net, or_key):
    write_config(home, config_with(primary=PAID_DIRECT))

    assert watcher.check_and_rotate({"rotation_count": 0}) is False
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == PAID_DIRECT
    assert not any("openrouter.ai" in u for u in net.urls())


def test_watcher_logs_user_primary_once(home, net, or_key, capsys):
    write_config(home, config_with(primary=PAID_DIRECT))
    watcher.check_and_rotate({})
    watcher.check_and_rotate({})
    out = capsys.readouterr().out
    assert out.count("user-configured, not touching it") == 1


def test_rotate_refuses_user_owned_primary(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary=PAID_OR))
    code, out = run_cli(monkeypatch, "rotate", "--force")
    assert code == 1
    assert "will not test or replace it" in out
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == PAID_OR
    assert net.calls == []


def test_freeride_set_primary_still_rotates(home, net, or_key, monkeypatch):
    run_cli(monkeypatch, "auto")
    assert read_state(home)["managed_primary"] == BEST

    # The managed primary starts failing; everything else works.
    def chat(payload):
        if payload["model"] == "vendor-a/model-a:free":
            return FakeResponse(503)
        return FakeResponse(200, {})
    net.post_routes[OR_CHAT_URL] = chat

    changed = watcher.check_and_rotate({"rotation_count": 0})

    assert changed is True
    new_primary = read_config(home)["agents"]["defaults"]["model"]["primary"]
    assert new_primary == ref("vendor-b/model-b:free")
    state = read_state(home)
    assert state["managed_primary"] == new_primary
    assert state["primary_owner"] == "freeride"


def test_watcher_bootstrap_marks_managed(home, net, or_key):
    write_config(home, config_with())
    net.post_routes[OR_CHAT_URL] = lambda payload: FakeResponse(200, {})

    assert watcher.check_and_rotate({"rotation_count": 0}) is True

    primary = read_config(home)["agents"]["defaults"]["model"]["primary"]
    state = read_state(home)
    assert state["primary_owner"] == "freeride"
    assert state["managed_primary"] == primary == BEST


# ---------- auto -f ----------

def test_auto_fallback_only_keeps_primary_and_pins_owner(home, net, or_key, monkeypatch):
    run_cli(monkeypatch, "auto")                    # FreeRide owns a free primary
    code, out = run_cli(monkeypatch, "auto", "-f")  # user says: keep this one
    assert code == 0

    cfg = read_config(home)
    assert cfg["agents"]["defaults"]["model"]["primary"] == BEST
    assert read_state(home)["primary_owner"] == "user"

    # Even a failing probe would not matter now: the watcher doesn't probe it.
    net.post_routes[OR_CHAT_URL] = lambda payload: FakeResponse(503)
    net.calls.clear()
    assert watcher.check_and_rotate({}) is False
    assert net.calls == []
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == BEST


def test_auto_fallback_only_keeps_paid_primary(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary=PAID_OR))
    code, _ = run_cli(monkeypatch, "auto", "-f")
    assert code == 0
    model = read_config(home)["agents"]["defaults"]["model"]
    assert model["primary"] == PAID_OR
    assert model["fallbacks"][0] == ROUTER
    assert all(f.endswith(":free") or f == ROUTER for f in model["fallbacks"])


def test_auto_fallback_only_keeps_user_fallbacks(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary=PAID_OR, fallbacks=[USER_FB, ROUTER]))
    run_cli(monkeypatch, "auto", "-f")
    fallbacks = read_config(home)["agents"]["defaults"]["model"]["fallbacks"]
    assert fallbacks[0] == USER_FB
    assert ROUTER in fallbacks

    # A second refresh keeps it too, and doesn't duplicate FreeRide entries.
    run_cli(monkeypatch, "auto", "-f")
    again = read_config(home)["agents"]["defaults"]["model"]["fallbacks"]
    assert again == fallbacks


def test_fallbacks_command_keeps_user_fallbacks(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary=PAID_OR, fallbacks=[USER_FB]))
    code, _ = run_cli(monkeypatch, "fallbacks", "-c", "3")
    assert code == 0
    fallbacks = read_config(home)["agents"]["defaults"]["model"]["fallbacks"]
    assert fallbacks == [USER_FB, ROUTER, BEST, ref("vendor-b/model-b:free")]
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == PAID_OR


# ---------- previous primary saved ----------

def test_previous_primary_persisted_before_auto(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary=PAID_OR, fallbacks=[USER_FB]))
    code, out = run_cli(monkeypatch, "auto")
    assert code == 0
    assert "saved first" in out

    prev = read_state(home)["previous"]
    assert prev["primary"] == PAID_OR
    assert prev["fallbacks"] == [USER_FB]
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == BEST


def test_previous_not_overwritten_by_freeride_value(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary=PAID_OR))
    run_cli(monkeypatch, "auto")
    run_cli(monkeypatch, "auto")
    run_cli(monkeypatch, "rotate", "--force")
    run_cli(monkeypatch, "auto", "-f")
    run_cli(monkeypatch, "auto", "-f")
    assert read_state(home)["previous"]["primary"] == PAID_OR


def test_user_change_after_auto_becomes_new_previous(home, net, or_key, monkeypatch):
    run_cli(monkeypatch, "auto")
    cfg = read_config(home)
    cfg["agents"]["defaults"]["model"]["primary"] = PAID_DIRECT  # user edits by hand
    write_config(home, cfg)
    run_cli(monkeypatch, "auto")
    assert read_state(home)["previous"]["primary"] == PAID_DIRECT


# ---------- restore ----------

def test_restore_puts_back_previous_primary_and_fallbacks(home, net, or_key, monkeypatch):
    user_models = {PAID_OR: {"alias": "mine"}, USER_FB: {}}
    write_config(home, config_with(primary=PAID_OR, fallbacks=[USER_FB], models=user_models))
    run_cli(monkeypatch, "auto")
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == BEST

    code, out = run_cli(monkeypatch, "restore")
    assert code == 0, out

    cfg = read_config(home)
    assert cfg["agents"]["defaults"]["model"] == {"primary": PAID_OR, "fallbacks": [USER_FB]}
    # Only the keys FreeRide added are removed; the user's own stay as they were.
    assert cfg["agents"]["defaults"]["models"] == user_models
    state = read_state(home)
    assert state["previous"] is None
    assert state["primary_owner"] == "user"

    # And the watcher now leaves it alone.
    net.calls.clear()
    assert watcher.check_and_rotate({}) is False
    assert net.calls == []


def test_restore_dry_run_writes_nothing(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary=PAID_OR))
    run_cli(monkeypatch, "auto")
    before = (home / "openclaw.json").read_bytes()
    state_before = (home / ".freeride-state.json").read_bytes()

    code, out = run_cli(monkeypatch, "restore", "--dry-run")

    assert code == 0
    assert PAID_OR in out and "Dry run" in out
    assert (home / "openclaw.json").read_bytes() == before
    assert (home / ".freeride-state.json").read_bytes() == state_before


def test_restore_noop_without_state(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary=PAID_OR))
    before = (home / "openclaw.json").read_bytes()
    code, out = run_cli(monkeypatch, "restore")
    assert code == 0
    assert "Nothing to restore" in out
    assert (home / "openclaw.json").read_bytes() == before
    assert not (home / ".freeride-state.json").exists()


def test_restore_to_no_primary(home, net, or_key, monkeypatch):
    run_cli(monkeypatch, "auto")
    code, _ = run_cli(monkeypatch, "restore")
    assert code == 0
    assert "primary" not in read_config(home)["agents"]["defaults"]["model"]


# ---------- first run after upgrade ----------

def test_migration_infers_owner_from_free_ref(home):
    cfg = config_with(primary=BEST, fallbacks=[ROUTER, USER_FB])
    state = main.load_state(cfg)
    assert state["primary_owner"] == "freeride"
    assert state["managed_primary"] == BEST
    assert state["managed_fallbacks"] == [ROUTER]
    assert main.primary_is_managed(state, BEST)


def test_migration_infers_user_owner_from_paid_ref(home):
    for primary in (PAID_OR, PAID_DIRECT, "openrouter/openrouter/auto", "google/gemini-3-pro-preview"):
        state = main.load_state(config_with(primary=primary, fallbacks=[ROUTER, USER_FB]))
        assert state["primary_owner"] == "user", primary
        assert state["previous"]["primary"] == primary
        assert state["previous"]["fallbacks"] == [USER_FB]
        assert not main.primary_is_managed(state, primary)


def test_migration_without_primary(home):
    state = main.load_state(config_with())
    assert state["primary_owner"] is None
    assert state["previous"] is None


def test_user_model_entry_settings_preserved(home, net, or_key, monkeypatch):
    models = {BEST: {"alias": "fast", "params": {"temperature": 0.2}}}
    write_config(home, config_with(models=models))
    run_cli(monkeypatch, "auto")
    assert read_config(home)["agents"]["defaults"]["models"][BEST] == models[BEST]
    assert BEST not in read_state(home)["added_model_keys"]
