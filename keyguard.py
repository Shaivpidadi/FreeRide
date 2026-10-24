"""
Keep API keys out of FreeRide's output.

`mask_key()` is the only way a key is ever shown (in `freeride status`).
`redact()` scrubs anything key-shaped out of text that came from somewhere
else, such as exception messages, before it is printed.
"""

import re

# Known key prefixes, longest first so `sk-or-v1-` wins over `sk-`.
_KNOWN_PREFIXES = ("sk-or-v1-", "gsk_", "csk-", "AIza", "sk-")

_PATTERNS = [
    re.compile(r"sk-or-v1-[A-Za-z0-9]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{12,}"),
    re.compile(r"\bcsk-[A-Za-z0-9]{12,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    # Any bearer credential, whatever its shape.
    re.compile(r"(?i)(bearer\s+)[^\s'\"\\]+"),
    # KEY=value pairs that name a secret.
    re.compile(r"(?i)\b([A-Z0-9_]*(?:API_KEY|API_TOKEN|TOKEN|SECRET)[A-Z0-9_]*\s*=\s*)[^\s'\"\\]+"),
]

REDACTED = "***"


def mask_key(key) -> str:
    """Show a key as its well-known prefix plus the last 4 characters.

      sk-or-v1-0123...abcd  ->  sk-or-v1-...abcd
      short or unknown      ->  ***
    """
    if not isinstance(key, str):
        return REDACTED
    key = key.strip()
    if len(key) < 16:
        return REDACTED
    prefix = ""
    for p in _KNOWN_PREFIXES:
        if key.startswith(p):
            prefix = p
            break
    return f"{prefix}...{key[-4:]}"


def redact(text) -> str:
    """Return `text` with credential-shaped substrings replaced by ***."""
    if text is None:
        return ""
    out = str(text)
    for pat in _PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + REDACTED, out)
        else:
            out = pat.sub(REDACTED, out)
    return out
