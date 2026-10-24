"""Opt-in providers: off by default, explicit consent for Gemini, only
routable tool-capable refs, never a paid OpenRouter slug."""

import argparse
import importlib.util
import json
import shutil
import subprocess

import pytest

import main
import providers
from conftest import (
    BEST, OR_CATALOG, OR_MODELS_URL, ROOT, ROUTER, config_with, read_config, read_state, ref, run_cli,
    write_config,
)

GROQ_REF = "groq/openai/gpt-oss-120b"
GEMINI_REF = "google/gemini-3-flash-preview"
CEREBRAS_REF = "cerebras/qwen-3-235b-a22b-instruct-2507"
OTHER_PREFIXES = ("groq/", "google/", "cerebras/")


def fallbacks(home):
    return read_config(home)["agents"]["defaults"]["model"]["fallbacks"]


def provider_urls(net):
    hosts = ("api.groq.com", "generativelanguage.googleapis.com", "api.cerebras.ai")
    return [u for u in net.urls() if any(h in u for h in hosts)]


# ---------- default: OpenRouter only ----------

def test_default_is_openrouter_only(home, provider_net, openclaw, or_key, all_provider_keys, monkeypatch):
    code, _ = run_cli(monkeypatch, "auto")
    assert code == 0
    assert fallbacks(home) == [ROUTER] + [ref(f"vendor-{c}/model-{c}:free") for c in "bcde"]
    assert not any(f.startswith(OTHER_PREFIXES) for f in fallbacks(home))
    assert provider_urls(provider_net) == []
    assert openclaw.calls == []
    assert read_state(home)["providers"] == []


def _load_v1_main(tmp_path):
    """The pre-1.1.0 main.py from git history, for a behavior comparison."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    proc = subprocess.run(["git", "-C", str(ROOT), "show", "3ca969f:main.py"], capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip("v1.0 main.py not in this checkout's history")
    src = tmp_path / "main_v1.py"
    src.write_text(proc.stdout)
    spec = importlib.util.spec_from_file_location("main_v1", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("argv", [
    ["auto"], ["auto", "-c", "3"], ["auto", "-f"], ["fallbacks"], ["fallbacks", "-c", "8"],
    ["switch", "model-c"], ["switch", "model-c", "-f"],
])
@pytest.mark.parametrize("start", [
    config_with(gateway={"port": 1}),
    config_with(primary=BEST, fallbacks=[ROUTER, ref("vendor-b/model-b:free")], gateway={"port": 1}),
])
def test_no_opt_in_output_matches_v1(home, tmp_path, net, openclaw, or_key, all_provider_keys,
                                     monkeypatch, argv, start):
    """With provider keys present but no opt-in, the config FreeRide writes is
    the same as what 1.0 wrote: same primary, same fallbacks in the same
    order, same allowlist entries (JSON object key order aside)."""
    net.get_routes[OR_MODELS_URL] = {"data": OR_CATALOG}  # no paid models: 1.0 had a looser free filter
    old = _load_v1_main(tmp_path)
    old_dir = tmp_path / "v1"
    old_dir.mkdir()
    monkeypatch.setattr(old, "OPENCLAW_CONFIG_PATH", old_dir / "openclaw.json")
    monkeypatch.setattr(old, "CACHE_FILE", old_dir / ".freeride-cache.json")
    (old_dir / "openclaw.json").write_text(json.dumps(start, indent=2))
    write_config(home, start)

    monkeypatch.setattr("sys.argv", ["freeride"] + argv)
    parsed = _v1_args(argv)
    {"auto": old.cmd_auto, "fallbacks": old.cmd_fallbacks, "switch": old.cmd_switch}[argv[0]](parsed)
    code, _ = run_cli(monkeypatch, *argv)

    assert code == 0
    new_cfg = json.loads((home / "openclaw.json").read_text())
    old_cfg = json.loads((old_dir / "openclaw.json").read_text())
    assert new_cfg == old_cfg
    assert new_cfg["agents"]["defaults"]["model"] == old_cfg["agents"]["defaults"]["model"]  # incl. order
    assert openclaw.calls == []


def _v1_args(argv):
    cmd, rest = argv[0], argv[1:]
    p = argparse.ArgumentParser()
    if cmd == "auto":
        p.add_argument("-c", "--fallback-count", type=int, default=5)
        p.add_argument("-f", "--fallback-only", action="store_true")
        p.add_argument("--setup-auth", action="store_true")
    elif cmd == "fallbacks":
        p.add_argument("-c", "--count", type=int, default=5)
    else:
        p.add_argument("model")
        p.add_argument("-f", "--fallback-only", action="store_true")
        p.add_argument("--no-fallbacks", action="store_true")
        p.add_argument("--setup-auth", action="store_true")
    return p.parse_args(rest)


def test_never_writes_paid_openrouter_slug(home, net, or_key, monkeypatch):
    run_cli(monkeypatch, "auto", "-c", "20")
    run_cli(monkeypatch, "rotate", "--force", "-c", "20")
    model = read_config(home)["agents"]["defaults"]["model"]
    written = [model["primary"]] + model["fallbacks"]
    written += list(read_config(home)["agents"]["defaults"]["models"])
    assert all(r == ROUTER or r.endswith(":free") for r in written), written
    assert not any("claude-paid" in r or "output-paid" in r for r in written)

    code, out = run_cli(monkeypatch, "switch", "claude-paid")
    assert code == 1
    assert "not found in free models" in out


def test_paid_output_model_is_not_free():
    paid_out = {"id": "x/y", "pricing": {"prompt": "0", "completion": "0.001"}}
    free = {"id": "x/z", "pricing": {"prompt": "0", "completion": "0"}}
    assert main.filter_free_models([paid_out, free]) == [free]


# ---------- Groq ----------

def test_groq_only_tool_models(home, provider_net, openclaw, or_key, all_provider_keys, monkeypatch):
    code, out = run_cli(monkeypatch, "auto", "--providers", "groq")
    assert code == 0, out
    fb = fallbacks(home)
    assert fb[:2] == [ROUTER, GROQ_REF]
    assert len(fb) == 5
    groq_refs = [f for f in fb if f.startswith("groq/")]
    assert groq_refs == [GROQ_REF]
    # qwen/qwen3-32b is live and in OpenClaw's catalog but has no tool metadata.
    assert "groq/qwen/qwen3-32b" not in fb


def test_groq_falls_back_to_next_tool_model(home, provider_net, openclaw, or_key, all_provider_keys,
                                            monkeypatch):
    provider_net.get_routes[providers.PROVIDERS["groq"].models_url] = {"data": [
        {"id": "openai/gpt-oss-20b"}, {"id": "qwen/qwen3-32b"}]}
    run_cli(monkeypatch, "auto", "--providers", "groq")
    assert "groq/openai/gpt-oss-20b" in fallbacks(home)


def test_groq_skipped_when_plugin_missing(home, provider_net, openclaw, or_key, all_provider_keys,
                                          monkeypatch):
    openclaw.plugins.discard("groq")
    code, out = run_cli(monkeypatch, "auto", "--providers", "groq")
    assert code == 0
    assert not any(f.startswith("groq/") for f in fallbacks(home))
    assert "openclaw plugins install @openclaw/groq-provider" in out
    assert provider_urls(provider_net) == []  # no key is used before the plugin check passes


def test_provider_skipped_when_openclaw_missing(home, provider_net, or_key, all_provider_keys, monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda name: None)
    code, out = run_cli(monkeypatch, "auto", "--providers", "groq,cerebras")
    assert code == 0
    assert not any(f.startswith(OTHER_PREFIXES) for f in fallbacks(home))
    assert "could not run `openclaw plugins list`" in out


def test_ref_must_be_in_openclaw_catalog(home, provider_net, openclaw, or_key, all_provider_keys,
                                         monkeypatch):
    openclaw.catalog["groq"] = ["groq/openai/gpt-oss-20b"]  # OpenClaw doesn't know 120b
    run_cli(monkeypatch, "auto", "--providers", "groq")
    assert "groq/openai/gpt-oss-20b" in fallbacks(home)
    assert GROQ_REF not in fallbacks(home)


def test_groq_skipped_without_key(home, provider_net, openclaw, or_key, monkeypatch):
    code, out = run_cli(monkeypatch, "auto", "--providers", "groq")
    assert code == 0
    assert "GROQ_API_KEY is not set" in out
    assert not any(f.startswith("groq/") for f in fallbacks(home))


# ---------- Gemini ----------

def test_gemini_requires_training_consent(home, provider_net, openclaw, or_key, all_provider_keys,
                                          monkeypatch):
    code, out = run_cli(monkeypatch, "auto", "--providers", "gemini")
    assert code == 0
    assert "--allow-training-providers" in out
    assert "improve its products" in out
    assert not any(f.startswith("google/") for f in fallbacks(home))
    assert provider_urls(provider_net) == []
    assert read_state(home)["providers"] == []


def test_gemini_with_consent_writes_flash_only(home, provider_net, openclaw, or_key, all_provider_keys,
                                               monkeypatch):
    code, out = run_cli(monkeypatch, "auto", "--providers", "gemini", "--allow-training-providers")
    assert code == 0, out
    assert "improve its products" in out  # the data-use note is shown when enabling
    google = [f for f in fallbacks(home) if f.startswith("google/")]
    assert google == [GEMINI_REF]
    state = read_state(home)
    assert state["providers"] == ["gemini"]
    assert state["allow_training"] == ["gemini"]


def test_gemini_consent_via_env(home, provider_net, openclaw, or_key, all_provider_keys, monkeypatch):
    monkeypatch.setenv("FREERIDE_PROVIDERS", "gemini")
    monkeypatch.setenv("FREERIDE_ALLOW_TRAINING", "gemini")
    run_cli(monkeypatch, "auto")
    assert GEMINI_REF in fallbacks(home)


@pytest.mark.parametrize("model_id,ok", [
    ("gemini-3-flash-preview", True),
    ("models/gemini-3.1-flash-lite-preview", True),
    ("gemini-flash-latest", True),
    ("gemma-4-31b-it", True),
    ("gemini-3-pro-preview", False),
    ("gemini-2.5-flash", False),
    ("gemini-1.5-flash", False),
    ("gemini-embedding-001", False),
    ("gemini-3-flash-image-preview", False),
    ("gemini-3-flash-tts", False),
    ("gemini-live-3-flash", False),
    ("text-embedding-004", False),
])
def test_gemini_filter_matches_v3_rules(model_id, ok):
    assert providers.gemini_is_free(model_id) is ok


def test_gemini_ranking_prefers_full_flash():
    gemini = providers.PROVIDERS["gemini"]
    ids = ["models/gemma-4-31b-it", "models/gemini-3.1-flash-lite-preview", "models/gemini-3-flash-preview"]
    assert providers.free_tool_candidates(gemini, ids) == [
        "gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "gemma-4-31b-it"]


# ---------- Cerebras ----------

def test_cerebras_last_and_tool_probed(home, provider_net, openclaw, or_key, all_provider_keys, monkeypatch):
    code, out = run_cli(monkeypatch, "auto", "--providers", "cerebras")
    assert code == 0, out
    fb = fallbacks(home)
    assert fb[-1] == CEREBRAS_REF
    # llama3.1-8b answered without a tool call; gpt-oss-120b is a known-broken id.
    assert "cerebras/llama3.1-8b" not in fb
    assert "cerebras/gpt-oss-120b" not in fb
    probed = provider_net.posted_models(providers.PROVIDERS["cerebras"].chat_url)
    assert probed == ["llama3.1-8b", "qwen-3-235b-a22b-instruct-2507"]


def test_cerebras_dropped_when_no_model_calls_tools(home, provider_net, openclaw, or_key,
                                                    all_provider_keys, monkeypatch):
    from conftest import text_response
    provider_net.post_routes[providers.PROVIDERS["cerebras"].chat_url] = lambda payload: text_response()
    run_cli(monkeypatch, "auto", "--providers", "cerebras")
    assert not any(f.startswith("cerebras/") for f in fallbacks(home))


# ---------- ordering, probing, persistence ----------

def test_fallback_order_groq_gemini_cerebras(home, provider_net, openclaw, or_key, all_provider_keys,
                                            monkeypatch):
    code, out = run_cli(monkeypatch, "auto", "--providers", "cerebras,gemini,groq", "--allow-training-providers")
    assert code == 0, out
    assert read_config(home)["agents"]["defaults"]["model"]["primary"] == BEST
    assert fallbacks(home) == [ROUTER, GROQ_REF, GEMINI_REF, ref("vendor-b/model-b:free"), CEREBRAS_REF]


def test_fallback_count_stays_a_total(home, provider_net, openclaw, or_key, all_provider_keys, monkeypatch):
    run_cli(monkeypatch, "auto", "-c", "8", "--providers", "groq,cerebras")
    fb = fallbacks(home)
    assert len(fb) == 8
    assert fb[0] == ROUTER and fb[1] == GROQ_REF and fb[-1] == CEREBRAS_REF


def test_probe_uses_provider_chat_url(home, provider_net, openclaw, or_key, all_provider_keys, monkeypatch):
    run_cli(monkeypatch, "auto", "--providers", "groq")
    groq = providers.PROVIDERS["groq"]
    assert provider_net.posted_models(groq.chat_url) == ["openai/gpt-oss-120b"]
    assert "openai/gpt-oss-120b" not in provider_net.posted_models(main.OPENROUTER_CHAT_URL)
    # The probe carries a tool definition, and the Groq key, not the OpenRouter one.
    payload = [p for m, u, p in provider_net.calls if u == groq.chat_url][0]
    assert payload["tools"][0]["function"]["name"] == "ping"


def test_providers_choice_persisted_and_opt_out(home, provider_net, openclaw, or_key, all_provider_keys,
                                                monkeypatch):
    run_cli(monkeypatch, "auto", "--providers", "groq")
    assert read_state(home)["providers"] == ["groq"]

    run_cli(monkeypatch, "fallbacks")  # remembered
    assert GROQ_REF in fallbacks(home)

    run_cli(monkeypatch, "rotate", "--force")  # the watcher path uses it too
    assert GROQ_REF in fallbacks(home)

    run_cli(monkeypatch, "fallbacks", "--providers", "openrouter")
    assert read_state(home)["providers"] == []
    assert not any(f.startswith("groq/") for f in fallbacks(home))


def test_provider_refs_removed_by_restore(home, provider_net, openclaw, or_key, all_provider_keys,
                                          monkeypatch):
    write_config(home, config_with(primary="anthropic/claude-x"))
    run_cli(monkeypatch, "auto", "--providers", "groq")
    run_cli(monkeypatch, "restore")
    cfg = read_config(home)
    assert cfg["agents"]["defaults"]["model"] == {"primary": "anthropic/claude-x"}
    assert cfg["agents"]["defaults"]["models"] == {}


@pytest.mark.parametrize("bad", ["nvidia", "huggingface", "cloudflare", "ollama", "groq,bogus"])
def test_unsupported_provider_rejected(home, net, or_key, monkeypatch, bad):
    write_config(home, config_with(primary="anthropic/claude-x"))
    before = (home / "openclaw.json").read_bytes()
    code, out = run_cli(monkeypatch, "auto", "--providers", bad)
    assert code == 2
    assert "unsupported provider" in out
    assert (home / "openclaw.json").read_bytes() == before
    assert net.calls == []


def test_bad_env_provider_rejected(home, net, or_key, monkeypatch):
    monkeypatch.setenv("FREERIDE_PROVIDERS", "nvidia")
    code, out = run_cli(monkeypatch, "auto")
    assert code == 2
    assert "unsupported provider" in out


def test_no_provider_writes_keys_or_provider_blocks(home, provider_net, openclaw, or_key, all_provider_keys,
                                                    monkeypatch):
    run_cli(monkeypatch, "auto", "--providers", "groq,gemini,cerebras", "--allow-training-providers")
    cfg = read_config(home)
    assert set(cfg) == {"agents"}
    assert "models" not in cfg  # no models.providers block
    text = (home / "openclaw.json").read_text()
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY", "apiKey", "baseUrl"):
        assert name not in text
