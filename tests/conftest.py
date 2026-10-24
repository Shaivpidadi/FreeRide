"""Shared fixtures. No test touches the network or the real ~/.openclaw."""

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import providers  # noqa: E402
import watcher  # noqa: E402

OR_MODELS_URL = main.OPENROUTER_API_URL
OR_CHAT_URL = main.OPENROUTER_CHAT_URL

OR_KEY = "sk-or-v1-" + "a1b2c3d4e5f6a7b8c9d0" * 3 + "WXYZ"
GROQ_KEY = "gsk_" + "Q" * 40 + "9876"
GEMINI_KEY = "AIza" + "G" * 35
CEREBRAS_KEY = "csk-" + "c" * 40 + "5432"

PROVIDER_ENV_VARS = (
    "OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    "CEREBRAS_API_KEY", "FREERIDE_PROVIDERS", "FREERIDE_ALLOW_TRAINING",
)


def or_model(model_id, context, prompt="0", completion="0"):
    return {
        "id": model_id,
        "context_length": context,
        "created": 0,
        "pricing": {"prompt": prompt, "completion": completion},
        "supported_parameters": ["tools", "temperature"],
        "architecture": {"output_modalities": ["text"]},
    }


# Vendors are deliberately not in TRUSTED_PROVIDERS, so rank == context order.
OR_CATALOG = [
    or_model("vendor-a/model-a:free", 900_000),
    or_model("vendor-b/model-b:free", 800_000),
    or_model("openrouter/free", 2_000_000),
    or_model("vendor-c/model-c:free", 700_000),
    or_model("vendor-d/model-d:free", 600_000),
    or_model("vendor-e/model-e:free", 500_000),
    or_model("vendor-f/model-f:free", 400_000),
    or_model("vendor-g/model-g:free", 300_000),
]
PAID_MODELS = [
    or_model("anthropic/claude-paid", 1_000_000, prompt="0.000003", completion="0.000015"),
    # Free input but paid output is still paid.
    or_model("vendor-x/output-paid", 990_000, prompt="0", completion="0.00001"),
]


def ref(model_id):
    return main.format_model_for_openclaw(model_id)


ROUTER = "openrouter/openrouter/free"
BEST = ref("vendor-a/model-a:free")


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body


def tool_call_response():
    return FakeResponse(200, {"choices": [{"message": {
        "role": "assistant",
        "tool_calls": [{"id": "1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}],
    }}]})


def text_response():
    return FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": "pong"}}]})


class FakeNet:
    """Stands in for requests.get/post, routed by URL. Any URL without a
    route fails the test."""

    def __init__(self):
        self.calls = []
        self.get_routes = {}
        self.post_routes = {}

    def get(self, url, headers=None, timeout=None, **kwargs):
        self.calls.append(("GET", url, None))
        if url not in self.get_routes:
            raise AssertionError(f"unexpected GET {url}")
        route = self.get_routes[url]
        return route() if callable(route) else FakeResponse(200, route)

    def post(self, url, headers=None, json=None, timeout=None, **kwargs):
        self.calls.append(("POST", url, json))
        if url not in self.post_routes:
            raise AssertionError(f"unexpected POST {url}")
        return self.post_routes[url](json)

    def posted_models(self, url):
        return [payload.get("model") for method, u, payload in self.calls if method == "POST" and u == url]

    def urls(self):
        return [u for _, u, _ in self.calls]


class FakeOpenClaw:
    """Stands in for the `openclaw` CLI used by the provider routing check."""

    def __init__(self):
        self.plugins = {"groq", "google", "cerebras"}
        self.catalog = {
            "groq": ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b", "groq/qwen/qwen3-32b",
                     "groq/llama-3.3-70b-versatile"],
            "google": ["google/gemini-3-flash-preview", "google/gemini-2.5-flash", "google/gemini-3-pro-preview",
                       "google/gemma-4-31b-it", "google/gemini-3.1-flash-lite-preview"],
            "cerebras": ["cerebras/llama3.1-8b", "cerebras/qwen-3-235b-a22b-instruct-2507",
                         "cerebras/gpt-oss-120b"],
        }
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        banner = "OpenClaw 2026.5.6 (test)\n\n"
        if args[:2] == ["plugins", "list"]:
            plugins = [{"id": p, "providerIds": [p], "enabled": True, "status": "loaded"} for p in sorted(self.plugins)]
            return banner + json.dumps({"plugins": plugins})
        if args[:2] == ["models", "list"]:
            prov = args[args.index("--provider") + 1]
            keys = self.catalog.get(prov, []) if prov in self.plugins else []
            return banner + json.dumps({"count": len(keys), "models": [{"key": k} for k in keys]})
        return None


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point every FreeRide path at a temp ~/.openclaw and clear key env vars."""
    oc = tmp_path / ".openclaw"
    oc.mkdir()
    monkeypatch.setattr(main, "OPENCLAW_CONFIG_PATH", oc / "openclaw.json")
    monkeypatch.setattr(main, "CACHE_FILE", oc / ".freeride-cache.json")
    monkeypatch.setattr(main, "STATE_FILE", oc / ".freeride-state.json")
    monkeypatch.setattr(main, "BACKUP_FILE", oc / "openclaw.json.freeride-bak")
    monkeypatch.setattr(main, "DOTENV_PATH", oc / ".env")
    monkeypatch.setattr(watcher, "STATE_FILE", oc / ".freeride-watcher-state.json")
    monkeypatch.setattr(watcher, "_skipped_primary", None)
    monkeypatch.setattr(main, "_RATE_LIMITED_KEYS", {})
    for name in PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return oc


@pytest.fixture
def net(monkeypatch):
    fake = FakeNet()
    fake.get_routes[OR_MODELS_URL] = {"data": OR_CATALOG + PAID_MODELS}
    fake.post_routes[OR_CHAT_URL] = lambda payload: text_response()
    monkeypatch.setattr(requests, "get", fake.get)
    monkeypatch.setattr(requests, "post", fake.post)
    return fake


@pytest.fixture
def openclaw(monkeypatch):
    fake = FakeOpenClaw()
    monkeypatch.setattr(providers, "_run_openclaw", fake)
    return fake


@pytest.fixture
def or_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", OR_KEY)
    return OR_KEY


@pytest.fixture
def provider_net(net):
    """Live /models and chat routes for Groq, Gemini and Cerebras."""
    groq = providers.PROVIDERS["groq"]
    gemini = providers.PROVIDERS["gemini"]
    cerebras = providers.PROVIDERS["cerebras"]
    net.get_routes[groq.models_url] = {"data": [
        {"id": "qwen/qwen3-32b"}, {"id": "openai/gpt-oss-20b"}, {"id": "openai/gpt-oss-120b"},
        {"id": "qwen/qwen3.6-27b"},
    ]}
    net.post_routes[groq.chat_url] = lambda payload: tool_call_response()
    net.get_routes[gemini.models_url] = {"data": [
        {"id": "models/gemini-3-pro-preview"}, {"id": "models/gemini-2.5-flash"},
        {"id": "models/gemma-4-31b-it"}, {"id": "models/gemini-3.1-flash-lite-preview"},
        {"id": "models/gemini-3-flash-preview"}, {"id": "models/text-embedding-004"},
    ]}
    net.post_routes[gemini.chat_url] = lambda payload: tool_call_response()
    net.get_routes[cerebras.models_url] = {"data": [
        {"id": "gpt-oss-120b"}, {"id": "llama3.1-8b"}, {"id": "qwen-3-235b-a22b-instruct-2507"},
    ]}
    # llama3.1-8b answers in text instead of calling the tool.
    net.post_routes[cerebras.chat_url] = lambda payload: (
        text_response() if payload["model"] == "llama3.1-8b" else tool_call_response())
    return net


@pytest.fixture
def all_provider_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("CEREBRAS_API_KEY", CEREBRAS_KEY)


def write_config(home, config):
    path = home / "openclaw.json"
    path.write_text(json.dumps(config, indent=2))
    return path


def read_config(home):
    return json.loads((home / "openclaw.json").read_text())


def read_state(home):
    return json.loads((home / ".freeride-state.json").read_text())


def config_with(primary=None, fallbacks=None, models=None, **extra):
    model = {}
    if primary is not None:
        model["primary"] = primary
    if fallbacks is not None:
        model["fallbacks"] = fallbacks
    config = {"agents": {"defaults": {"model": model, "models": models or {}}}}
    config.update(extra)
    return config


def run_cli(monkeypatch, *argv):
    """Run `freeride <argv>`; returns (exit_code, stdout)."""
    monkeypatch.setattr(sys, "argv", ["freeride"] + list(argv))
    out = io.StringIO()
    code = 0
    with redirect_stdout(out):
        try:
            main.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue()
