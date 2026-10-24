# 🎢 FreeRide

### Stop paying for AI. Start riding free.

[![ClawHub Downloads](https://api.clawhub-badge.xyz/badge/free-ride/downloads.svg)](https://clawhub.ai/skills/free-ride)
[![ClawHub Current Installs](https://api.clawhub-badge.xyz/badge/free-ride/installs-current.svg)](https://clawhub.ai/skills/free-ride)
[![ClawHub Stars](https://api.clawhub-badge.xyz/badge/free-ride/stars.svg)](https://clawhub.ai/skills/free-ride)
[![ClawHub Version](https://api.clawhub-badge.xyz/badge/free-ride/version.svg)](https://clawhub.ai/skills/free-ride)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![OpenClaw Compatible](https://img.shields.io/badge/OpenClaw-Compatible-blue.svg)](https://github.com/openclaw/openclaw)
---

> ## 🚀 Want more than OpenClaw + OpenRouter? Try FreeRide v3
>
> This skill (1.x) is a small config writer: it picks OpenRouter free models
> for OpenClaw and writes them into `openclaw.json`.
> **[FreeRide v3](https://github.com/Shaivpidadi/FreeRideV3)** is a local
> gateway on `localhost:11343` that routes every request across free tiers
> (OpenRouter, Gemini, Groq, Ollama Cloud, Z.ai, NVIDIA NIM, Cloudflare and
> more) and fails over **inside the same response** when one rate-limits.
> It works with OpenClaw, Aider, Continue, Hermes, OpenCode, the Claude /
> Codex / Gemini CLIs, and anything that speaks the OpenAI API.
>
> ```bash
> uv tool install freeride-gateway==0.4.0a28   # or: pipx install freeride-gateway==0.4.0a28
> freeride init                                  # asks for keys, stores them in ~/.freeride/.env
> freeride serve
> freeride bind openclaw                         # points OpenClaw at the gateway
> ```
>
> See [Should I use v3?](#should-i-use-1x-or-v3) below for the differences before you switch.
> 👉 **Repo:** https://github.com/Shaivpidadi/FreeRideV3 · **Site:** https://free-ride.xyz

---

**FreeRide** gives you unlimited free AI in [OpenClaw](https://github.com/openclaw/openclaw) by automatically managing OpenRouter's free models.

```
You: *hits rate limit*
FreeRide: "I got you." *switches to next best model*
You: *keeps coding*
```

## The Problem

You're using OpenClaw. You love it. But:

- 💸 API costs add up fast
- 🚫 Free models have rate limits
- 😤 Manually switching models is annoying
- 🤷 You don't know which free model is actually good

## The Solution

One command. Free AI. Forever.

```bash
freeride auto
```

That's it. FreeRide:

1. **Finds** the 30+ free models on OpenRouter
2. **Ranks** them by quality (context length, capabilities, speed)
3. **Sets** the best one as your primary
4. **Configures** smart fallbacks for when you hit rate limits
5. **Preserves** your existing OpenClaw config

## Installation

```bash
npx clawhub@0.23.3 --workdir ~/.openclaw/workspace install @shaivpidadi/free-ride --version 1.1.0
cd ~/.openclaw/workspace/skills/@shaivpidadi/free-ride
pip install -e .
```

The command pins the ClawHub CLI version, the skill owner (`@shaivpidadi`), and the skill version. `requests` is capped below 3.

That's it. `freeride` and `freeride-watcher` are now available as global commands.

## Quick Start

### 1. Get a Free OpenRouter Key

Go to [openrouter.ai/keys](https://openrouter.ai/keys) → Create account → Generate key

No credit card. No trial. Actually free.

### 2. Set Your Key

Open `~/.openclaw/.env` in your editor and add a line (OpenClaw reads this file too):

```
OPENROUTER_API_KEY=<your key>
```

Several keys are also accepted: `OPENROUTER_API_KEY=["<key 1>","<key 2>"]`. You can export the variable in your shell profile instead.

Don't paste keys into an agent chat or onto a command line, where they end up in history and logs. `freeride status` shows whether a key is set, masked like `sk-or-v1-...abcd`. FreeRide reads keys from the environment, `~/.openclaw/.env`, and the `env` block of `openclaw.json`; it never writes them.

### 3. Run FreeRide

```bash
freeride auto
```

### 4. Restart OpenClaw

```bash
openclaw gateway restart
```

### 5. Verify It Works

Message your agent on WhatsApp/Telegram/Discord or the dashboard:

```
You:    /status
Agent:  (shows the free model name + token count)
```

Done. You're now running on free AI with automatic fallbacks.

## What You Get

```
Primary Model: openrouter/nvidia/nemotron-3-nano-30b-a3b:free (256K context)

Fallbacks:
  1. openrouter/free          ← Smart router (auto-picks best available)
  2. qwen/qwen3-coder:free    ← Great for coding
  3. stepfun/step-3.5:free    ← Fast responses
  4. deepseek/deepseek:free   ← Strong reasoning
  5. mistral/mistral:free     ← Reliable fallback
```

When you hit a rate limit, OpenClaw automatically tries the next model. You keep working. No interruptions.

## Commands

| Command | What it does |
|---------|--------------|
| `freeride auto` | Auto-configure best model + fallbacks |
| `freeride list` | See all 30+ free models ranked |
| `freeride switch <model>` | Use a specific model |
| `freeride status` | Check your current setup |
| `freeride fallbacks` | Update fallbacks only |
| `freeride refresh` | Force refresh model cache |
| `freeride rotate` | Live-test primary; swap to a working model if it's failing (only a primary FreeRide set) |
| `freeride restore` | Put back the primary and fallbacks you had before FreeRide (`--dry-run` to preview) |

### Pro Tips

```bash
# Already have a model you like (even a paid one)? Keep it, just add fallbacks.
# FreeRide marks it as yours and never changes it:
freeride auto -f

# Changed your mind? Put back what you had before:
freeride restore --dry-run
freeride restore

# Want more fallbacks for maximum uptime?
freeride auto -c 10

# Coding? Switch to the best coding model:
freeride switch qwen3-coder

# See what's available:
freeride list -n 30

# Always restart OpenClaw after changes:
openclaw gateway restart
```

## Optional Providers (opt-in)

OpenRouter free models stay the default, and nothing changes unless you opt in. You can add other free tiers to the fallback chain:

```bash
freeride auto --providers groq,cerebras
freeride auto --providers groq,gemini --allow-training-providers
freeride auto --providers openrouter     # back to OpenRouter only
```

| Provider | Key | What FreeRide adds | Position |
|----------|-----|--------------------|----------|
| Groq | `GROQ_API_KEY` | A tool-capable free model, e.g. `groq/openai/gpt-oss-120b` | Right after `openrouter/free` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | A Flash / Flash-Lite / Gemma model, e.g. `google/gemini-3-flash-preview` | After Groq |
| Cerebras | `CEREBRAS_API_KEY` | A model that passes a live tool-call check | Last |

- **Gemini needs explicit consent** (`--allow-training-providers`). Google may use prompts sent on the unpaid tier to improve its products. EEA/UK/CH accounts are paid-only.
- FreeRide only writes a `groq/`, `google/` or `cerebras/` ref when the OpenClaw plugin is loaded and OpenClaw already lists that model (`openclaw plugins list`, `openclaw models list --provider ...`). Otherwise it skips the provider and prints the `openclaw plugins install ...` command for you to run.
- Put the keys in `~/.openclaw/.env` like the OpenRouter key. FreeRide never writes keys or provider blocks.
- The choice is remembered for later runs and for the watcher. `FREERIDE_PROVIDERS=groq,cerebras` and `FREERIDE_ALLOW_TRAINING=gemini` work the same as the flags.
- The fallback count (`-c`) is still a total: with `-c 5` and all three enabled you get `openrouter/free`, Groq, Gemini, one OpenRouter free model, Cerebras.

## How It Ranks Models

FreeRide scores each model (0-1) based on:

| Factor | Weight | Why |
|--------|--------|-----|
| Context Length | 40% | Longer = handle bigger codebases |
| Capabilities | 30% | Vision, tools, structured output |
| Recency | 20% | Newer models = better performance |
| Provider Trust | 10% | Google, Meta, NVIDIA, etc. |

The **smart fallback** `openrouter/free` is always first - it auto-selects based on what your request needs.

## Testing with Your OpenClaw Agent

After running `freeride auto` and `openclaw gateway restart`:

```bash
# Check OpenClaw sees the models
openclaw models list

# Validate config
openclaw config validate

# Open the dashboard and chat
openclaw dashboard
# Or message your agent on WhatsApp/Telegram/Discord
```

Useful agent commands to verify:

| Command | What it tells you |
|---------|-------------------|
| `/status` | Current model + token usage |
| `/model` | Available models (your free models should be listed) |
| `/new` | Start fresh session with the new model |

## Watcher (Background Daemon)

The watcher is a long-running process that probes your current primary model
every minute and rotates the config the moment it starts failing. Because it
runs **outside** the agent's inference loop, it can recover from a "everything
is 429" deadlock that the agent itself can't escape (the agent would need
inference to call `freeride rotate`, but inference is exactly what's broken).

```bash
# Foreground (good for trying it out)
freeride-watcher

# Background, persistent across logout
nohup freeride-watcher > ~/.openclaw/freeride-watcher.log 2>&1 &

# One-off check (no loop)
freeride-watcher --once

# See state (rotation count, last reason)
freeride-watcher --status

# Custom interval (seconds)
freeride-watcher --interval 120
```

For an actual service, point your favorite supervisor (launchd, systemd,
tmux, pm2) at `freeride-watcher`. There is no PID file — stop it with
`Ctrl-C` or `kill <pid>`.

The watcher only probes and rotates a primary that FreeRide set. If you set
your own primary (or kept it with `freeride auto -f`), the watcher logs
"primary is user-configured, not touching it" once and leaves it alone. It
never sends test requests to a model you chose.

## FAQ

**Is this actually free?**

Yes. OpenRouter provides free tiers for many models. You just need an account (no credit card).

**What about rate limits?**

Three layers of defense:
1. **OpenClaw's runtime fallback chain** — when the primary returns 429, the gateway transparently tries fallback 1, 2, 3 at routing time. The agent never sees the 429.
2. **`openrouter/free` smart router** is always fallback #1 — server-side smart routing onto whatever free model is actually available.
3. **`freeride-watcher` daemon** — runs in the background, probes the primary every 60s, rotates the config the moment it starts failing. This is what saves you when the entire fallback chain is dead and the agent has nothing left to route to.

If you've set multiple keys via `OPENROUTER_API_KEY='["key1","key2"]'`, every layer above also rotates through them on 429.

**Will it mess up my OpenClaw config?**

No. FreeRide only touches `agents.defaults.model.primary`, `agents.defaults.model.fallbacks` and entries under `agents.defaults.models`. Your gateway, channels, plugins, workspace, customInstructions - all preserved. Fallbacks you added yourself are kept.

Before every change it saves a copy to `~/.openclaw/openclaw.json.freeride-bak` and writes the new file atomically. If your `openclaw.json` has JSON5 comments or trailing commas, or uses `$include`, FreeRide refuses to write it rather than risk losing anything.

**What exactly does FreeRide write?**

| Path | What |
|------|------|
| `~/.openclaw/openclaw.json` | `agents.defaults.model.primary`, `agents.defaults.model.fallbacks`, `agents.defaults.models.<model-ref>`; `auth.profiles["openrouter:default"]` only with `--setup-auth` (shown first, needs your yes or `--yes`) |
| `~/.openclaw/openclaw.json.freeride-bak` | Copy of your config taken before each write |
| `~/.openclaw/.freeride-state.json` | Which primary/fallbacks FreeRide set, and what you had before |
| `~/.openclaw/.freeride-cache.json` | 6-hour cache of OpenRouter's model list |
| `~/.openclaw/.freeride-watcher-state.json` | Watcher rotation count |
| `*.freeride-tmp`, `*.tmp` | Short-lived files used for atomic writes |

It never writes API keys, never writes `~/.openclaw/.env`, and never touches `auth-profiles.json`. `--setup-auth` adds `{"provider": "openrouter", "mode": "api_key"}`, which only tells OpenClaw to use your `OPENROUTER_API_KEY`.

**I'm upgrading from 1.0.x. What changes for me?**

- The first time you run any command, FreeRide works out who owns your primary. An OpenRouter `:free` model (or `openrouter/free`) counts as FreeRide's; anything else, including a paid model, counts as yours and is saved for `freeride restore`. If you hand-picked a free model and want it left alone, run `freeride auto -f`.
- The watcher and `freeride rotate` stop touching a primary you set.
- If an older FreeRide already replaced your paid primary, it was never saved, so `restore` can't bring it back. Set it again yourself (and then `freeride auto -f` to keep it).
- Nothing else changes unless you opt into extra providers.

**Which models are free?**

Run `freeride list` to see current availability. It changes, which is why FreeRide exists.

**Do I need to restart OpenClaw after changes?**

Yes. Run `openclaw gateway restart` after any FreeRide command that changes your config.

## The Math

| Scenario | Monthly Cost |
|----------|--------------|
| GPT-4 API | $50-200+ |
| Claude API | $50-200+ |
| OpenClaw + FreeRide | **$0** |

You're welcome.

## Requirements

- [OpenClaw](https://github.com/openclaw/openclaw) installed (Node ≥22)
- Python 3.8+
- Free OpenRouter account ([get key](https://openrouter.ai/keys))
- Optional: Groq / Gemini / Cerebras keys if you opt into those providers

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  You         │ ──→ │  FreeRide    │ ──→ │  OpenRouter API  │
│  "freeride   │     │              │     │  (30+ free       │
│   auto"      │     │  • Fetch     │     │   models)        │
└──────────────┘     │  • Rank      │     └──────────────────┘
                     │  • Configure │
                     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐
                     │ ~/.openclaw/ │
                     │ openclaw.json│
                     └──────┬───────┘
                            │
                     openclaw gateway restart
                            │
                            ▼
                     ┌──────────────┐
                     │  OpenClaw    │
                     │  (free AI!)  │
                     └──────────────┘
```

## Should I use 1.x or v3?

| | FreeRide 1.x (this skill) | FreeRide v3 |
|---|---|---|
| What it is | Writes model refs into `openclaw.json`, then gets out of the way | A local gateway process that serves every request |
| Agents | OpenClaw | OpenClaw, Aider, Continue, Hermes, OpenCode, Claude / Codex / Gemini CLIs, any OpenAI-compatible client |
| Providers | OpenRouter free models; Groq, Gemini, Cerebras opt-in | OpenRouter, Gemini, Groq, Ollama Cloud, Z.ai, NVIDIA NIM, Cloudflare, local Ollama and more |
| When a model fails | OpenClaw walks the fallback list; `freeride-watcher` rotates the primary | The gateway retries the next provider inside the same request |
| Runs in the background | Nothing (the watcher is optional) | `freeride serve` must be running |
| Network calls of its own | Only to the model providers | Model providers, plus an hourly aggregate usage beacon that is on by default (`freeride telemetry` shows it, `freeride telemetry off` stops it) |

Stay on 1.x if you only use OpenClaw and want nothing running in the background. Move to v3 if you use other agents, keep hitting OpenRouter's daily limit, or want failover that doesn't depend on a fallback list.

**Switching from 1.x to v3:**

```bash
freeride restore --dry-run      # optional: see what you had before FreeRide
freeride restore                # optional: put it back first
pip uninstall freeride          # v3 installs its own `freeride` and `freeride-watcher` commands
uv tool install freeride-gateway==0.4.0a28
freeride init && freeride serve
freeride bind openclaw
openclaw gateway restart
```

Stop `freeride-watcher` from 1.x before you switch. `freeride bind openclaw` adds a `models.providers.freeride` block and an `auth.profiles["freeride:default"]` pointer, and sets the primary to a `freeride/...` ref. FreeRide 1.x treats that primary as yours and never replaces it. v3 also has `freeride auto` / `list` / `switch` for OpenClaw; those follow 1.0.x behavior and don't have 1.1.0's ownership tracking or `restore`.

## Contributing

Found a bug? Want a feature? PRs welcome.

```bash
cd ~/.openclaw/workspace/skills/@shaivpidadi/free-ride   # skills/free-ride for older installs

# Test commands
freeride list
freeride status
freeride auto --help

# Run the test suite (no network needed)
pip install -e ".[test]"
python -m pytest -q
```

## Related Projects

- [OpenClaw](https://github.com/openclaw/openclaw) - The AI coding agent
- [OpenRouter](https://openrouter.ai) - The model router
- [ClawHub](https://github.com/clawhub) - Skill marketplace

## License

MIT - Do whatever you want.

---

<p align="center">
  <b>Stop paying. Start riding.</b>
  <br>
  <br>
  <a href="https://github.com/Shaivpidadi/FreeRide">⭐ Star us on GitHub</a>
  ·
  <a href="https://openrouter.ai/keys">🔑 Get OpenRouter Key</a>
  ·
  <a href="https://github.com/openclaw/openclaw">🦞 Install OpenClaw</a>
</p>
