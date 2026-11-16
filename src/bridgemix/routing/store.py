"""
Persistent application-routing rules.

A rule maps a stable application key (PulseAudio ``application.process.binary``,
e.g. ``"zen"`` / ``"Discord"``) to a Bridge Cast *channel* ("Chat", "Music"…).
Rules survive relaunches and are re-applied to matching streams as they appear;
`backend.resolve_target` turns a channel into the sink that carries it now, so a
rule still works when the device shows up under another sink name (other USB
port, firmware or audio profile).  Older versions saved a sink name instead;
those rules are still accepted.

File: ``~/.config/bridgemix/routing.json`` ::

    {
      "rules": {
        "Discord": "Chat",
        "zen":     "Music"
      }
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_ROUTING_PATH = Path.home() / ".config" / "bridgemix" / "routing.json"


def routing_path() -> Path:
    return _ROUTING_PATH


def load_rules() -> dict[str, str]:
    """Return the saved {app_key: channel} rules.

    Never raises: a missing or malformed file yields an empty rule set so the
    app keeps working with no routing configured.
    """
    try:
        raw = json.loads(_ROUTING_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        log.warning("Could not read routing rules %s: %s", _ROUTING_PATH, exc)
        return {}

    rules = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(rules, dict):
        return {}
    # Keep only well-typed string→string entries.
    return {k: v for k, v in rules.items() if isinstance(k, str) and isinstance(v, str)}


def save_rules(rules: dict[str, str]) -> None:
    """Write the full rule set, creating the config dir if needed."""
    _ROUTING_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ROUTING_PATH.write_text(json.dumps({"rules": rules}, indent=2))
    log.info("Routing rules saved to %s (%d rules)", _ROUTING_PATH, len(rules))


def set_rule(app_key: str, channel: str) -> dict[str, str]:
    """Add/replace one rule and persist; returns the updated rule set."""
    rules = load_rules()
    rules[app_key] = channel
    save_rules(rules)
    return rules


def remove_rule(app_key: str) -> dict[str, str]:
    """Drop one rule (no-op if absent) and persist; returns the updated set."""
    rules = load_rules()
    if rules.pop(app_key, None) is not None:
        save_rules(rules)
    return rules
