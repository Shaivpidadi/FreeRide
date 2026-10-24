"""openclaw.json is never wiped, always backed up, and written atomically.
--setup-auth asks before writing."""

import io
import json
import os
import stat
import sys

import pytest

import main
import watcher
from conftest import BEST, config_with, read_config, run_cli, write_config

COMMENTED = """{
  // my settings
  "gateway": {"port": 18789},
  "channels": {"telegram": {"enabled": true}},
  "agents": {"defaults": {"model": {"primary": "anthropic/claude-x"}}},
}
"""


def test_commented_config_is_refused_and_untouched(home, net, or_key, monkeypatch):
    path = home / "openclaw.json"
    path.write_text(COMMENTED)

    for argv in (["auto"], ["auto", "-f"], ["fallbacks"], ["switch", "model-b"], ["rotate", "-f"]):
        code, out = run_cli(monkeypatch, *argv)
        assert code == 2, argv
        assert "not plain JSON" in out
        assert "Nothing was written" in out
        assert path.read_text() == COMMENTED

    assert not (home / "openclaw.json.freeride-bak").exists()
    assert not (home / ".freeride-state.json").exists()
    assert net.calls == []  # refused before touching the network


def test_watcher_does_not_touch_commented_config(home, net, or_key, capsys):
    path = home / "openclaw.json"
    path.write_text(COMMENTED)
    assert watcher.check_and_rotate({}) is False
    assert path.read_text() == COMMENTED
    assert "Not touching the config" in capsys.readouterr().out


def test_watcher_once_exits_cleanly_on_include(home, net, or_key, monkeypatch, capsys):
    write_config(home, {"$include": "./more.json5"})
    with pytest.raises(SystemExit) as exc:
        watcher.run_once()
    assert exc.value.code == 2
    assert json.loads((home / "openclaw.json").read_text()) == {"$include": "./more.json5"}


def test_include_config_refused(home, net, or_key, monkeypatch):
    cfg = {"$include": "./agents.json5", "gateway": {"port": 1}}
    write_config(home, cfg)
    before = (home / "openclaw.json").read_bytes()
    code, out = run_cli(monkeypatch, "auto")
    assert code == 2
    assert "$include" in out
    assert (home / "openclaw.json").read_bytes() == before


def test_empty_config_file_is_treated_as_new(home, net, or_key, monkeypatch):
    (home / "openclaw.json").write_text("")
    code, _ = run_cli(monkeypatch, "auto")
    assert code == 0
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == BEST


def test_backup_written_before_change(home, net, or_key, monkeypatch):
    original = config_with(primary="anthropic/claude-x", gateway={"port": 18789})
    write_config(home, original)
    before = (home / "openclaw.json").read_bytes()

    run_cli(monkeypatch, "auto")

    assert (home / "openclaw.json.freeride-bak").read_bytes() == before
    cfg = read_config(home)
    assert cfg["gateway"] == {"port": 18789}
    assert cfg["agents"]["defaults"]["model"]["primary"] == BEST


def test_write_is_atomic_and_keeps_mode(home, net, or_key, monkeypatch):
    path = write_config(home, config_with(gateway={"port": 1}))
    os.chmod(path, 0o600)
    before = path.read_bytes()

    def crash(src, dst):
        raise OSError("disk full")
    with monkeypatch.context() as m:
        m.setattr(main.os, "replace", crash)
        with pytest.raises(OSError):
            main.save_openclaw_config({"agents": {}})
    assert path.read_bytes() == before  # a failed write leaves the old file intact
    assert not list(home.glob("*.freeride-tmp"))

    main.save_openclaw_config({"agents": {}})
    assert json.loads(path.read_text()) == {"agents": {}}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_new_config_file_is_private(home, net, or_key, monkeypatch):
    run_cli(monkeypatch, "auto")
    assert stat.S_IMODE((home / "openclaw.json").stat().st_mode) == 0o600


# ---------- --setup-auth ----------

def test_setup_auth_requires_confirmation_noninteractive(home, net, or_key, monkeypatch):
    write_config(home, config_with(primary="anthropic/claude-x"))
    before = (home / "openclaw.json").read_bytes()
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    code, out = run_cli(monkeypatch, "auto", "--setup-auth")

    assert code == 1
    assert 'auth.profiles["openrouter:default"]' in out
    assert "--yes" in out
    assert (home / "openclaw.json").read_bytes() == before
    assert not (home / ".freeride-state.json").exists()
    assert net.calls == []


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_setup_auth_declined_on_tty(home, net, or_key, monkeypatch):
    write_config(home, config_with())
    before = (home / "openclaw.json").read_bytes()
    monkeypatch.setattr(sys, "stdin", _Tty("n\n"))
    code, out = run_cli(monkeypatch, "switch", "model-b", "--setup-auth")
    assert code == 1
    assert "Cancelled" in out
    assert (home / "openclaw.json").read_bytes() == before


def test_setup_auth_accepted_on_tty(home, net, or_key, monkeypatch):
    write_config(home, config_with())
    monkeypatch.setattr(sys, "stdin", _Tty("y\n"))
    code, _ = run_cli(monkeypatch, "auto", "--setup-auth")
    assert code == 0
    assert read_config(home)["auth"]["profiles"]["openrouter:default"] == {
        "provider": "openrouter", "mode": "api_key"}


def test_setup_auth_writes_only_profile_pointer(home, net, or_key, monkeypatch):
    write_config(home, config_with(gateway={"port": 1}))
    code, _ = run_cli(monkeypatch, "auto", "--setup-auth", "--yes")
    assert code == 0
    cfg = read_config(home)
    assert set(cfg) == {"agents", "auth", "gateway"}
    assert cfg["auth"] == {"profiles": {"openrouter:default": {"provider": "openrouter", "mode": "api_key"}}}


def test_setup_auth_existing_profile_left_alone(home, net, or_key, monkeypatch):
    profile = {"provider": "openrouter", "mode": "api_key", "note": "mine"}
    write_config(home, config_with(auth={"profiles": {"openrouter:default": profile}}))
    code, out = run_cli(monkeypatch, "auto", "--setup-auth")  # no --yes needed: nothing to add
    assert code == 0
    assert "already exists" in out
    assert read_config(home)["auth"]["profiles"]["openrouter:default"] == profile
