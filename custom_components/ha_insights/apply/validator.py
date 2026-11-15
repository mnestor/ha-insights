"""Layer 1 (offline) automation-payload validator.

Shape check only — verifies the dict matches the expected HA automation
config shape before we even try to apply. Layer 2 (online via WS
automation/validate) lands at step 13 and catches "entity doesn't exist"
or "service not registered in this HA version" issues.
"""
from __future__ import annotations

from typing import Any

from ..lib.automation_keys import actions_of, trigger_platform, triggers_of

_VALID_MODES = frozenset({"single", "restart", "queued", "parallel"})


def validate_automation(payload: dict[str, Any]) -> list[str]:
    """Validate an automation payload's shape. Returns list of error strings.

    Empty list means valid. Caller decides whether to surface, suppress, or
    block apply based on the result.
    """
    errors: list[str] = []

    triggers = triggers_of(payload)
    if triggers is None:
        errors.append("missing 'trigger'")
    elif not isinstance(triggers, list):
        errors.append("'trigger' must be a list")
    elif not triggers:
        errors.append("'trigger' must not be empty")
    else:
        for i, trigger in enumerate(triggers):
            if not isinstance(trigger, dict):
                errors.append(f"trigger[{i}] must be a dict")
            elif trigger_platform(trigger) is None:
                errors.append(f"trigger[{i}] missing 'platform'")

    actions = actions_of(payload)
    if actions is None:
        errors.append("missing 'action'")
    elif not isinstance(actions, list):
        errors.append("'action' must be a list")
    elif not actions:
        errors.append("'action' must not be empty")
    else:
        for i, action in enumerate(actions):
            if not isinstance(action, dict):
                errors.append(f"action[{i}] must be a dict")

    mode = payload.get("mode")
    if mode is not None and mode not in _VALID_MODES:
        errors.append(
            f"'mode' must be one of {sorted(_VALID_MODES)}; got {mode!r}"
        )

    return errors
