"""API keys are never shown in full, and docs never tell anyone to print one."""

import json
import re

import pytest
import requests

import main
from conftest import (
    CEREBRAS_KEY, GEMINI_KEY, GROQ_KEY, OR_KEY, OR_MODELS_URL, ROOT, config_with, run_cli, write_config,
)
from keyguard import mask_key, redact


def test_mask_key_shows_only_prefix_and_last4():
    assert mask_key(OR_KEY) == "sk-or-v1-...WXYZ"
    assert mask_key(GROQ_KEY) == "gsk_...9876"
    assert mask_key(CEREBRAS_KEY) == "csk-...5432"
    assert mask_key(GEMINI_KEY) == "AIza...GGGG"
    assert mask_key("x" * 30 + "1234") == "...1234"


@pytest.mark.parametrize("short", ["", "abc", "sk-or-v1-abc", None, 123])
def test_mask_key_short_or_odd_values(short):
    assert mask_key(short) == "***"


def test_status_never_prints_full_key(home, monkeypatch):
    keys = [OR_KEY, "sk-or-v1-" + "z" * 40 + "QRST"]
    monkeypatch.setenv("OPENROUTER_API_KEY", json.dumps(keys))
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    code, out = run_cli(monkeypatch, "status")
    assert code == 0
    for k in keys + [GROQ_KEY]:
        assert k not in out
    assert "sk-or-v1-...WXYZ" in out
    assert "sk-or-v1-...QRST" in out
    assert "groq: key set" in out


def test_status_single_key_masked(home, or_key, monkeypatch):
    code, out = run_cli(monkeypatch, "status")
    assert OR_KEY not in out
    assert "OpenRouter API Key: sk-or-v1-...WXYZ" in out


@pytest.mark.parametrize("secret", [
    OR_KEY, GROQ_KEY, GEMINI_KEY, CEREBRAS_KEY, "sk-" + "p" * 30,
])
def test_redact_scrubs_keys_in_exceptions(secret):
    text = f"Illegal header value b'{secret}' while connecting"
    assert secret not in redact(text)
    assert "***" in redact(text)


def test_redact_scrubs_bearer_and_env_pairs():
    assert "tok123secret" not in redact("Authorization: Bearer tok123secret")
    assert "hunter2" not in redact("GROQ_API_KEY=hunter2 failed")
    assert redact("nothing secret here") == "nothing secret here"


def test_network_error_is_redacted(home, or_key, monkeypatch, capsys):
    def boom(url, headers=None, timeout=None, **kw):
        raise requests.ConnectionError(f"bad header Bearer {OR_KEY}")
    monkeypatch.setattr(requests, "get", boom)
    assert main.fetch_all_models() == []
    out = capsys.readouterr().out
    assert OR_KEY not in out
    assert "network error" in out


def test_watcher_error_is_redacted(home, or_key, monkeypatch, capsys):
    import watcher

    def explode(state):
        raise RuntimeError(f"boom {OR_KEY}")
    monkeypatch.setattr(watcher, "check_and_rotate", explode)
    monkeypatch.setattr(watcher.time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(watcher.signal, "signal", lambda *a: None)
    with pytest.raises(KeyboardInterrupt):
        watcher.run_daemon(15)
    out = capsys.readouterr().out
    assert "Watcher error" in out
    assert OR_KEY not in out


DOC_FILES = ["SKILL.md", "README.md"]


@pytest.mark.parametrize("name", DOC_FILES)
def test_docs_have_no_echo_of_key(name):
    text = (ROOT / name).read_text()
    assert not re.search(r"echo\s+\$\{?\w*(API_KEY|TOKEN)", text)
    assert not re.search(r"printenv\s+\w*API_KEY", text)


@pytest.mark.parametrize("name", DOC_FILES)
def test_docs_have_no_config_set_with_literal_key(name):
    text = (ROOT / name).read_text()
    assert not re.search(r"config set env\.(vars\.)?\w*API_KEY", text)
    # No literal-looking key on an export line either.
    assert not re.search(r"export \w*API_KEY=['\"]?(sk-|gsk_|csk-|AIza)", text)


def test_key_resolution_order(home, monkeypatch):
    write_config(home, config_with(env={"vars": {"OPENROUTER_API_KEY": "from-env-vars"},
                                        "OPENROUTER_API_KEY": "from-legacy-env"}))
    assert main.get_api_keys() == ["from-env-vars"]

    (home / ".env").write_text("# comment\nexport OPENROUTER_API_KEY='from-dotenv'\n")
    assert main.get_api_keys() == ["from-dotenv"]

    monkeypatch.setenv("OPENROUTER_API_KEY", "from-process-env")
    assert main.get_api_keys() == ["from-process-env"]


def test_legacy_env_block_still_read(home):
    write_config(home, config_with(env={"OPENROUTER_API_KEY": ["k1", "k2"]}))
    assert main.get_api_keys() == ["k1", "k2"]


def test_gemini_key_alias(home, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", GEMINI_KEY)
    assert main.get_provider_keys("gemini") == [GEMINI_KEY]


def test_keys_never_written(home, net, or_key, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    run_cli(monkeypatch, "auto", "--setup-auth", "--yes")
    for path in home.iterdir():
        text = path.read_text()
        assert OR_KEY not in text, path
        assert GROQ_KEY not in text, path
    assert not (home / ".env").exists()
    assert OR_MODELS_URL  # sanity: the fake network served the run
