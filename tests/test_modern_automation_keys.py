"""Automations written with the current (HA 2024.10+) keys.

HA's automation editor saves ``triggers:`` / ``conditions:`` /
``actions:``, ``trigger: <platform>`` inside each trigger, and
``action: <service>`` inside each step. Every reader of user
automations must treat these exactly like the legacy
``trigger:`` / ``action:`` / ``platform:`` / ``service:`` form.
The legacy form stays covered by the existing tests.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from custom_components.ha_insights.apply import find_conflicts, validate_automation
from custom_components.ha_insights.audit.fixes import apply_deterministic_fixes
from custom_components.ha_insights.audit.rollup import collect_audit_target_entities
from custom_components.ha_insights.insight import Insight, InsightKind
from custom_components.ha_insights.lib.automation_keys import (
    actions_key,
    actions_of,
    conditions_of,
    step_service,
    trigger_platform,
    triggers_key,
    triggers_of,
)
from custom_components.ha_insights.llm.agent_client import _summarize_payload
from custom_components.ha_insights.llm.refiner import _looks_structurally_incomplete


def _modern_time_automation(at: str = "06:47:00") -> dict[str, Any]:
    """Shape the HA automation editor writes today."""
    return {
        "id": "1775426214143",
        "alias": "Kitchen lights on",
        "description": "",
        "triggers": [{"trigger": "time", "at": at}],
        "conditions": [{"condition": "time", "weekday": ["mon", "tue"]}],
        "actions": [
            {
                "action": "light.turn_on",
                "metadata": {},
                "data": {},
                "target": {"entity_id": "light.kitchen"},
            }
        ],
        "mode": "single",
    }


def _modern_state_automation() -> dict[str, Any]:
    return {
        "id": "2",
        "alias": "Send ticker on dishwasher done",
        "triggers": [
            {
                "trigger": "state",
                "entity_id": "sensor.bosch_dishwasher_operation_state",
                "to": "finished",
            }
        ],
        "conditions": [],
        "actions": [
            {"action": "ticker.notify", "data": {"message": "Dishes are done!"}},
            {"action": "light.turn_on", "target": {"entity_id": ["light.kitchen"]}},
            {"delay": {"hours": 1}},
        ],
        "mode": "single",
    }


# --- lib.automation_keys ---------------------------------------------------


def test_helpers_read_current_keys() -> None:
    auto = _modern_time_automation()
    assert triggers_of(auto) == auto["triggers"]
    assert conditions_of(auto) == auto["conditions"]
    assert actions_of(auto) == auto["actions"]
    assert trigger_platform(auto["triggers"][0]) == "time"
    assert step_service(auto["actions"][0]) == "light.turn_on"


def test_helpers_read_legacy_keys() -> None:
    auto = {
        "trigger": [{"platform": "state", "entity_id": "x"}],
        "condition": [],
        "action": [{"service": "light.turn_off"}],
    }
    assert triggers_of(auto) == auto["trigger"]
    assert conditions_of(auto) == []
    assert actions_of(auto) == auto["action"]
    assert trigger_platform(auto["trigger"][0]) == "state"
    assert step_service(auto["action"][0]) == "light.turn_off"


def test_helpers_prefer_current_key_when_both_present() -> None:
    auto = {"triggers": ["new"], "trigger": ["old"], "actions": ["new"], "action": ["old"]}
    assert triggers_of(auto) == ["new"]
    assert actions_of(auto) == ["new"]


def test_helpers_defaults_and_non_dicts() -> None:
    assert triggers_of({}) is None
    assert actions_of({}, []) == []
    assert triggers_of(None) is None
    assert trigger_platform("time") is None
    assert trigger_platform({"at": "07:00"}) is None
    assert step_service({"delay": 5}) is None


def test_write_keys_follow_existing_style() -> None:
    assert triggers_key({"triggers": []}) == "triggers"
    assert triggers_key({"trigger": []}) == "trigger"
    assert actions_key({"action": []}) == "action"
    assert actions_key({}) == "actions"


def test_helpers_do_not_mutate() -> None:
    auto = _modern_time_automation()
    before = repr(auto)
    triggers_of(auto)
    actions_of(auto)
    trigger_platform(auto["triggers"][0])
    triggers_key(auto)
    assert repr(auto) == before


# --- audit rollup target collection -----------------------------------------


def test_audit_targets_collected_from_modern_automations() -> None:
    targets = collect_audit_target_entities(
        [_modern_time_automation(), _modern_state_automation()]
    )
    assert targets == [
        "light.kitchen",
        "sensor.bosch_dishwasher_operation_state",
    ]


# --- conflict scanner --------------------------------------------------------


def _legacy_insight(at: str) -> Insight:
    return Insight(
        id="abc",
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="schedule",
        area_id=None,
        title="Test",
        confidence=0.9,
        fingerprint={"k": 1},
        payload={
            "trigger": [{"platform": "time", "at": at}],
            "action": [
                {"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}
            ],
        },
        payload_format="automation",
        created_at=datetime(2026, 5, 8, tzinfo=UTC),
    )


def test_conflict_with_modern_existing_automation() -> None:
    conflicts = find_conflicts(_legacy_insight("06:50:00"), [_modern_time_automation()])
    assert conflicts == ["1775426214143"]


def test_no_conflict_when_modern_time_is_far_apart() -> None:
    assert find_conflicts(_legacy_insight("12:00:00"), [_modern_time_automation()]) == []


# --- validator ---------------------------------------------------------------


def test_validator_accepts_modern_payload() -> None:
    assert validate_automation(_modern_time_automation()) == []


def test_validator_still_rejects_modern_trigger_without_platform() -> None:
    payload = _modern_time_automation()
    payload["triggers"] = [{"at": "06:47:00"}]
    assert validate_automation(payload) == ["trigger[0] missing 'platform'"]


# --- deterministic fixes keep the user's key style --------------------------


def test_trigger_drift_fix_on_modern_automation_keeps_plural_keys() -> None:
    auto = _modern_time_automation(at="07:00:00")
    refined, summaries = apply_deterministic_fixes(
        auto,
        [
            {
                "kind": "trigger_time_drift",
                "text": "...",
                "metrics": {"trigger_time": "07:00:00", "delta_min": 8.0},
            }
        ],
    )
    assert refined is not None
    assert refined["triggers"][0]["at"] == "07:10"
    assert "trigger" not in refined
    assert "action" not in refined
    assert "07:00:00 → 07:10" in summaries[0]


def test_trigger_drift_fix_wraps_single_modern_trigger_under_plural_key() -> None:
    auto = _modern_time_automation(at="07:00:00")
    auto["triggers"] = {"trigger": "time", "at": "07:00:00"}
    refined, _ = apply_deterministic_fixes(
        auto,
        [
            {
                "kind": "trigger_time_drift",
                "text": "",
                "metrics": {"trigger_time": "07:00:00", "delta_min": 8.0},
            }
        ],
    )
    assert refined is not None
    assert refined["triggers"] == [{"trigger": "time", "at": "07:10"}]
    assert "trigger" not in refined


# --- LLM helpers -------------------------------------------------------------


def test_prompt_summary_reads_modern_automation() -> None:
    summary = _summarize_payload(_modern_time_automation())
    assert "Trigger: time 06:47:00" in summary
    assert "Days: mon, tue" in summary
    assert "light.turn_on" in summary


def test_complete_modern_payload_not_flagged_as_truncated() -> None:
    assert _looks_structurally_incomplete(_modern_time_automation()) is False


def test_modern_payload_missing_actions_flagged_as_truncated() -> None:
    payload = _modern_time_automation()
    del payload["actions"]
    assert _looks_structurally_incomplete(payload) is True
