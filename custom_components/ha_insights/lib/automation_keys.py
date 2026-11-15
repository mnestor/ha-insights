"""Read automation configs written in either key style.

Home Assistant 2024.10 renamed the automation config keys:

  ===================  ====================
  legacy               current
  ===================  ====================
  ``trigger:``         ``triggers:``
  ``condition:``       ``conditions:``
  ``action:``          ``actions:``
  ``platform: state``  ``trigger: state``   (inside each trigger)
  ===================  ====================

HA accepts both forms and the automation editor saves the current one,
so most installs now hold the plural keys. Code that reads a user's
automations must accept both. These helpers read either form (current
keys win when both are present) and never mutate the dict passed in.

Pure functions, no HA imports.
"""
from __future__ import annotations

from typing import Any

_TRIGGERS = ("triggers", "trigger")
_CONDITIONS = ("conditions", "condition")
_ACTIONS = ("actions", "action")


def _pick(auto: Any, keys: tuple[str, str], default: Any) -> Any:
    if not isinstance(auto, dict):
        return default
    current, legacy = keys
    if current in auto:
        return auto[current]
    return auto.get(legacy, default)


def _key(auto: Any, keys: tuple[str, str]) -> str:
    current, legacy = keys
    if isinstance(auto, dict) and current not in auto and legacy in auto:
        return legacy
    return current


def triggers_of(auto: Any, default: Any = None) -> Any:
    """The automation's trigger block (``triggers`` or ``trigger``)."""
    return _pick(auto, _TRIGGERS, default)


def conditions_of(auto: Any, default: Any = None) -> Any:
    """The automation's condition block (``conditions`` or ``condition``)."""
    return _pick(auto, _CONDITIONS, default)


def actions_of(auto: Any, default: Any = None) -> Any:
    """The automation's action block (``actions`` or ``action``)."""
    return _pick(auto, _ACTIONS, default)


def triggers_key(auto: Any) -> str:
    """Key to write the trigger block back under, matching the
    automation's existing style. New/empty dicts get the current key."""
    return _key(auto, _TRIGGERS)


def actions_key(auto: Any) -> str:
    """Key to write the action block back under, matching the
    automation's existing style. New/empty dicts get the current key."""
    return _key(auto, _ACTIONS)


def step_service(step: Any) -> str | None:
    """The service an action step calls (``service:`` or, since 2024.8,
    ``action:``)."""
    if not isinstance(step, dict):
        return None
    service = step.get("service") or step.get("action")
    return service if isinstance(service, str) else None


def trigger_platform(trig: Any) -> str | None:
    """A single trigger's platform (``platform: time`` or ``trigger: time``)."""
    if not isinstance(trig, dict):
        return None
    platform = trig.get("platform")
    if isinstance(platform, str):
        return platform
    platform = trig.get("trigger")
    return platform if isinstance(platform, str) else None
