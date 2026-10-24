---
name: freeride
version: 1.1.0
description: Manages free AI models from OpenRouter for OpenClaw. Automatically ranks models by quality, configures fallbacks for rate-limit handling, and updates openclaw.json. Optional Groq, Gemini and Cerebras free tiers are opt-in. Use when the user mentions free AI, OpenRouter, model switching, rate limits, or wants to reduce AI costs.
env:
  - name: OPENROUTER_API_KEY
    description: OpenRouter API key — get a free one at openrouter.ai/keys
    required: true
    secret: true
  - name: GROQ_API_KEY
    description: Optional, only used with --providers groq
    required: false
    secret: true
  - name: GEMINI_API_KEY
    description: Optional (GOOGLE_API_KEY also accepted), only used with --providers gemini --allow-training-providers
    required: false
    secret: true
  - name: GOOGLE_API_KEY
    description: Optional alias for GEMINI_API_KEY
    required: false
    secret: true
  - name: CEREBRAS_API_KEY
    description: Optional, only used with --providers cerebras
    required: false
    secret: true
network:
  - openrouter.ai
  - api.groq.com (only with --providers groq)
  - generativelanguage.googleapis.com (only with --providers gemini)
  - api.cerebras.ai (only with --providers cerebras)
reads:
  - ~/.openclaw/openclaw.json
  - ~/.openclaw/.env (API keys, read only)
writes:
  - ~/.openclaw/openclaw.json (keys: agents.defaults.model.primary, agents.defaults.model.fallbacks, agents.defaults.models.<model-ref>; and auth.profiles.openrouter:default only with --setup-auth after confirmation)
  - ~/.openclaw/openclaw.json.freeride-tmp (temporary, replaced atomically)
  - ~/.openclaw/openclaw.json.freeride-bak (copy taken before every write)
  - ~/.openclaw/.freeride-state.json (+ .freeride-tmp sibling)
  - ~/.openclaw/.freeride-cache.json
  - ~/.openclaw/.freeride-watcher-state.json (+ .tmp sibling)
  - ~/.openclaw/freeride-watcher.log (only via the suggested nohup redirect)
  - ~/.openclaw/ (created if missing)
never-writes:
  - API keys, anywhere
  - ~/.openclaw/.env
  - auth-profiles.json
runs:
  - openclaw plugins list --json (read only, only with --providers)
  - openclaw models list --all --provider <id> --json (read only, only with --providers)
install: npx clawhub@0.23.3 --workdir ~/.openclaw/workspace install @shaivpidadi/free-ride --version 1.1.0 && cd ~/.openclaw/workspace/skills/@shaivpidadi/free-ride && pip install -e .
metadata:
  openclaw:
    emoji: "\U0001F3A2"
    homepage: https://github.com/Shaivpidadi/FreeRide
    requires:
      env:
        - OPENROUTER_API_KEY
      bins:
        - openclaw
      anyBins:
        - python3
        - python
    primaryEnv: OPENROUTER_API_KEY
    envVars:
      - name: OPENROUTER_API_KEY
        required: true
        description: OpenRouter API key, free at openrouter.ai/keys. Set it in ~/.openclaw/.env, never in chat.
      - name: GROQ_API_KEY
        required: false
        description: Groq key, used only with --providers groq.
      - name: GEMINI_API_KEY
        required: false
        description: Gemini key, used only with --providers gemini --allow-training-providers.
      - name: GOOGLE_API_KEY
        required: false
        description: Alias for GEMINI_API_KEY.
      - name: CEREBRAS_API_KEY
        required: false
        description: Cerebras key, used only with --providers cerebras.
      - name: FREERIDE_PROVIDERS
        required: false
        description: Same as --providers (e.g. groq,cerebras). Unset means OpenRouter only.
      - name: FREERIDE_ALLOW_TRAINING
        required: false
        description: Same as --allow-training-providers (e.g. gemini).
---

# FreeRide - Free AI for OpenClaw

## What This Skill Does

Configures OpenClaw to use **free** AI models from OpenRouter. Sets the best free model as primary, adds ranked fallbacks so rate limits don't interrupt the user, and preserves existing config.

## Rules for the agent

- **Never print, echo, log, or ask the user to paste an API key into chat.** Don't echo key variables, run `env` or `printenv`, or `cat ~/.openclaw/.env`. The user sets keys themselves.
- To check whether a key is set, run `freeride status`. It shows keys masked (for example `sk-or-v1-...abcd`) or `NOT SET`.
- Before running a command with `--setup-auth`, tell the user what it adds (see below) and only pass `--yes` once they agree.
- Don't pass `--providers` or `--allow-training-providers` unless the user asked for those providers. For Gemini, tell the user Google may use free-tier prompts for training before passing `--allow-training-providers`.

## Prerequisites

Before running any FreeRide command, ensure:

1. **OPENROUTER_API_KEY is set.** Check with `freeride status`. If it says `NOT SET`, the user gets a free key at https://openrouter.ai/keys and adds it themselves, in their editor, as a line in `~/.openclaw/.env`:
   ```
   OPENROUTER_API_KEY=<their key>
   ```
   (or exports it in their own shell). Do not type the key on a command line for them.

2. **The `freeride` CLI is installed.** Check with `which freeride`. If not found:
   ```bash
   cd ~/.openclaw/workspace/skills/@shaivpidadi/free-ride   # older installs: ~/.openclaw/workspace/skills/free-ride
   pip install -e .
   ```

## Primary Workflow

When the user wants free AI, run these steps in order:

```bash
# Step 1: Configure best free model + fallbacks
freeride auto

# Step 2: Restart gateway so OpenClaw picks up the changes
openclaw gateway restart
```

That's it. The user now has free AI with automatic fallback switching.

Verify by telling the user to send `/status` to check the active model.

If the user already has a primary model they want to keep (for example a paid one), use `freeride auto -f` instead. FreeRide then marks that primary as theirs and never changes it.

## Commands Reference

| Command | When to use it |
|---------|----------------|
| `freeride auto` | User wants free AI set up (most common). Saves their old primary first. |
| `freeride auto -f` | User wants fallbacks but wants to keep their current primary model |
| `freeride auto -c 10` | User wants more fallbacks (default is 5) |
| `freeride list` | User wants to see available free models |
| `freeride list -n 30` | User wants to see all free models |
| `freeride switch <model>` | User wants a specific model (e.g. `freeride switch qwen3-coder`) |
| `freeride switch <model> -f` | Add specific model as fallback only |
| `freeride status` | Check current FreeRide configuration (keys shown masked) |
| `freeride fallbacks` | Update only the fallback models |
| `freeride refresh` | Force refresh the cached model list |
| `freeride rotate` | User is rate-limited / fallback chain is dead — live-test and rebuild (only if FreeRide set the primary) |
| `freeride restore` | Put back the primary and fallbacks from before FreeRide changed them (`--dry-run` to preview) |

**After any command that changes config, always run `openclaw gateway restart`.**

## What It Writes

FreeRide updates only these keys in `~/.openclaw/openclaw.json`:

- `agents.defaults.model.primary` — e.g. `openrouter/qwen/qwen3-coder:free`
- `agents.defaults.model.fallbacks` — e.g. `["openrouter/openrouter/free", "openrouter/nvidia/nemotron:free", ...]`. Fallbacks the user added themselves are kept, ahead of FreeRide's.
- `agents.defaults.models.<model-ref>` — allowlist entries so `/model` shows the free models. Existing entries are left as they are.
- `auth.profiles["openrouter:default"]` = `{"provider": "openrouter", "mode": "api_key"}` — **only** with `--setup-auth`, after FreeRide shows this entry and the user confirms (or `--yes`). It tells OpenClaw to use `OPENROUTER_API_KEY`; it contains no key.

Everything else (gateway, channels, plugins, env, customInstructions, named agents) is preserved.

Before every write FreeRide copies the file to `~/.openclaw/openclaw.json.freeride-bak` and writes the new file atomically. If `openclaw.json` has JSON5 comments or trailing commas, or uses `$include`, FreeRide refuses to write it and says why.

Other files FreeRide writes, all under `~/.openclaw/`:

- `.freeride-state.json` — which primary/fallbacks FreeRide set, and the user's previous ones (for `freeride restore`)
- `.freeride-cache.json` — 6-hour cache of the OpenRouter model list
- `.freeride-watcher-state.json` — watcher rotation count and last reason
- temporary `*.freeride-tmp` / `*.tmp` siblings during atomic writes

FreeRide **never** writes API keys, never writes `~/.openclaw/.env`, and never touches `auth-profiles.json`.

The first fallback is always `openrouter/free` — OpenRouter's smart router that auto-picks the best available model based on the request.

## Who owns the primary

- A primary set by `freeride auto`, `freeride switch`, `freeride rotate` or the watcher is FreeRide's. FreeRide may rotate it when it fails.
- Any other primary (one the user set, a paid model, or one kept with `-f`) is the user's. FreeRide never tests it, never replaces it, and `freeride rotate` refuses to touch it.
- `freeride restore` puts back what was there before and hands the primary back to the user.

## Optional providers (opt-in)

OpenRouter free models stay the default. Only when the user asks, add more free tiers to the fallback chain:

```bash
freeride auto --providers groq,cerebras
freeride auto --providers groq,gemini --allow-training-providers   # Gemini needs explicit consent
freeride auto --providers openrouter                                # turn them off again
```

- **Groq** (`GROQ_API_KEY`): tool-capable models only, placed right after `openrouter/free`.
- **Gemini** (`GEMINI_API_KEY` or `GOOGLE_API_KEY`): Flash / Flash-Lite / Gemma only. Google may use prompts on the free tier for training, so it also needs `--allow-training-providers`.
- **Cerebras** (`CEREBRAS_API_KEY`): last in the chain, and only after a live tool-call check passes.

For each one FreeRide checks that the OpenClaw plugin is loaded (`openclaw plugins list`) and that OpenClaw already lists the model ref (`openclaw models list --provider ...`). If not, it skips the provider and prints the `openclaw plugins install ...` command for the user to run. FreeRide does not install plugins and never selects a paid OpenRouter model. The choice is remembered for later runs and the watcher. `FREERIDE_PROVIDERS` / `FREERIDE_ALLOW_TRAINING` env vars work the same as the flags.

## Watcher (Background Daemon)

For autonomous recovery from a "whole chain is rate-limited" deadlock — which
the agent can't fix by itself, since calling `freeride rotate` requires
inference and inference is exactly what's failing — the user can run a slim
background daemon:

```bash
# Foreground
freeride-watcher

# Persistent background (writes the log file ~/.openclaw/freeride-watcher.log)
nohup freeride-watcher > ~/.openclaw/freeride-watcher.log 2>&1 &

# One-shot check (no loop)
freeride-watcher --once

# State / history
freeride-watcher --status
```

The daemon probes the current primary every 60s, but only if FreeRide set it;
if it fails, it rebuilds the chain with live-verified models. A primary the
user configured is left alone. Recommend this whenever the user is leaving
an unattended OpenClaw setup running.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `freeride: command not found` | `cd ~/.openclaw/workspace/skills/@shaivpidadi/free-ride && pip install -e .` |
| `OPENROUTER_API_KEY not set` | User adds `OPENROUTER_API_KEY=...` to `~/.openclaw/.env` (key from https://openrouter.ai/keys) |
| `... is not plain JSON` | The config has comments or trailing commas. The user removes them, then re-runs. Nothing was written. |
| `rotate` says the primary is not FreeRide's | Expected for a user's own primary. `freeride auto` hands it to FreeRide (old one saved). |
| Want the old model back | `freeride restore --dry-run`, then `freeride restore` |
| Changes not taking effect | `openclaw gateway restart` then `/new` for fresh session |
| Agent shows 0 tokens | Check `freeride status` — primary should be `openrouter/<provider>/<model>:free` |
