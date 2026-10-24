"""The published skill matches what the code does: pinned install, one
version everywhere, every command and every write declared."""

import json
import re

import main
from conftest import ROOT, config_with, run_cli, write_config

SKILL_JSON = json.loads((ROOT / "skill.json").read_text())
SKILL_MD = (ROOT / "SKILL.md").read_text()
README = (ROOT / "README.md").read_text()


def _frontmatter(text):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md has no frontmatter"
    return match.group(1)


def test_install_command_is_pinned():
    for install in (SKILL_JSON["install"], re.search(r"^install: (.*)$", _frontmatter(SKILL_MD), re.M).group(1)):
        assert "@latest" not in install
        assert re.search(r"npx clawhub@\d+\.\d+\.\d+ ", install), install
        assert "install @shaivpidadi/free-ride --version " + SKILL_JSON["version"] in install
        assert "skills/@shaivpidadi/free-ride" in install
    assert "clawhub@latest" not in README
    assert "install @shaivpidadi/free-ride --version " + SKILL_JSON["version"] in README


def test_requests_is_capped():
    assert SKILL_JSON["dependencies"]["requests"] == ">=2.31.0,<3"
    assert (ROOT / "requirements.txt").read_text().strip() == "requests>=2.31.0,<3"
    assert '"requests>=2.31.0,<3"' in (ROOT / "setup.py").read_text()


def test_versions_agree():
    version = SKILL_JSON["version"]
    assert version == "1.1.0"
    assert f'version="{version}"' in (ROOT / "setup.py").read_text()
    assert f"version: {version}" in _frontmatter(SKILL_MD)
    assert (ROOT / "CHANGELOG.md").read_text().split("\n## ")[1].startswith(version)


def test_skill_json_lists_every_command(monkeypatch):
    code, out = run_cli(monkeypatch, "--help")
    listed = re.search(r"\{([a-z,]+)\}", out).group(1).split(",")
    assert sorted(listed) == sorted(SKILL_JSON["commands"])
    for cmd in listed:
        assert f"`freeride {cmd}" in SKILL_MD


def test_new_hosts_and_optional_secrets_declared():
    hosts = ["openrouter.ai", "api.groq.com", "generativelanguage.googleapis.com", "api.cerebras.ai"]
    assert SKILL_JSON["network"] == hosts
    assert SKILL_JSON["openclaw"]["networkAccess"] == hosts
    front = _frontmatter(SKILL_MD)
    for host in hosts:
        assert host in front
    assert SKILL_JSON["requiredEnv"] == ["OPENROUTER_API_KEY"]
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "CEREBRAS_API_KEY"):
        assert key in SKILL_JSON["openclaw"]["optionalSecrets"]
        assert SKILL_JSON["config"][key]["required"] is False
        assert f"name: {key}" in front


# Containers FreeRide edits inside; anything else is compared whole.
_CONTAINERS = {"agents", "agents.defaults", "agents.defaults.model", "agents.defaults.models",
               "auth", "auth.profiles"}


def _changed_config_keys(before, after, prefix=""):
    """Dotted paths of every key added or changed between two configs."""
    keys = set()
    for k, v in after.items():
        path = f"{prefix}{k}"
        old = before.get(k) if isinstance(before, dict) else None
        if path in _CONTAINERS and isinstance(v, dict):
            keys |= _changed_config_keys(old if isinstance(old, dict) else {}, v, path + ".")
        elif old != v:
            keys.add(path)
    return keys


def _declared_key(path):
    """Collapse per-model allowlist entries to the declared pattern."""
    if path.startswith("agents.defaults.models."):
        return "agents.defaults.models.<model-ref>"
    return path


def test_manifest_declares_all_writes(home, net, or_key, monkeypatch):
    before = config_with(primary="anthropic/claude-x", gateway={"port": 1})
    write_config(home, before)

    for argv in (["auto", "--setup-auth", "--yes"], ["fallbacks"], ["rotate", "-f"], ["auto", "-f"],
                 ["restore"]):
        code, out = run_cli(monkeypatch, *argv)
        assert code in (0, 1), (argv, out)
    import watcher
    watcher.check_and_rotate({"rotation_count": 0})
    watcher.save_state({"rotation_count": 0})

    # Files: every file FreeRide left in ~/.openclaw is declared.
    declared_files = " ".join(SKILL_JSON["writes"])
    front = _frontmatter(SKILL_MD)
    for path in home.iterdir():
        assert path.name in declared_files, path.name
        assert path.name in front, path.name
    assert main.BACKUP_FILE.name in declared_files

    # Config keys: run a full auto again and diff against the starting config.
    write_config(home, before)
    main.STATE_FILE.unlink()
    run_cli(monkeypatch, "auto", "--setup-auth", "--yes")
    after = json.loads((home / "openclaw.json").read_text())
    changed = {_declared_key(k) for k in _changed_config_keys(before, after)}
    declared_keys = " ".join(SKILL_JSON["openclaw"]["configKeys"])
    for key in changed:
        assert key in declared_keys or key.replace('"', "") in declared_keys, key
        assert key.split(".<")[0] in front, key
    assert "auth.profiles.openrouter:default" in changed


def test_setup_auth_declared_with_condition():
    keys = SKILL_JSON["openclaw"]["configKeys"]
    auth = [k for k in keys if k.startswith("auth.profiles")]
    assert auth and "--setup-auth" in auth[0]
    assert "auth-profiles.json" in " ".join(SKILL_JSON["neverWrites"])
    assert "auth-profiles.json" in SKILL_MD
