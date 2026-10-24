# Changelog

## 1.1.0

Hardening model selection and auth setup, plus opt-in providers.

- Your own primary model is now left alone. FreeRide only rotates a primary it set itself, and the watcher no longer probes or replaces a primary you configured.
- FreeRide saves your previous primary and fallbacks before changing them. New `freeride restore` (with `--dry-run`) puts them back.
- `freeride auto -f` keeps your primary, marks it as yours, and keeps your own fallback entries.
- API keys are always masked in output, and key-shaped text is scrubbed from error messages. Skill instructions no longer print keys or put them on a command line; keys go in `~/.openclaw/.env`.
- The install command pins the ClawHub CLI version, the skill owner and the skill version. `requests` is capped below 3.
- `--setup-auth` shows exactly what it will add and asks before writing (`--yes` for non-interactive runs). Every file and config key FreeRide writes is now listed in the skill manifest.
- FreeRide refuses to rewrite an `openclaw.json` it cannot parse (JSON5 comments, trailing commas, `$include`), backs the file up to `openclaw.json.freeride-bak` before every change, and writes it atomically.
- Existing per-model settings under `agents.defaults.models` are no longer reset.
- OpenRouter models that charge for output are no longer treated as free.
- Optional providers, off unless you enable them with `--providers`: Groq (tool-capable free models), Gemini (needs `--allow-training-providers`; Google may use free-tier prompts for training), and Cerebras (last, after a live tool-call check). OpenRouter free models stay the default.
- `skill.json` now lists the `rotate` and `restore` commands.
- Added a test suite (`python -m pytest`).
- SKILL.md declares its requirements in the `metadata.openclaw` block ClawHub reads: required and optional env vars (including `FREERIDE_PROVIDERS` and `FREERIDE_ALLOW_TRAINING`), the `openclaw` and Python binaries, and the homepage.
- New `.clawhubignore` keeps the tests out of the published skill.
- License is now MIT-0, matching ClawHub.
