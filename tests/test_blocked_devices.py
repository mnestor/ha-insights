"""Entity and device blocklists.

A blocked device blocks every entity registered to it, including
entities it gains after the option was set. Blocked entities never
enter the event buffer, so they cost no buffer capacity, and they are
excluded from scans and LLM prompts like `llm_block_entities` always
was. Devices connected *via* a blocked device are not blocked.
"""
from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.config_flow import (
    CONF_BLOCKED_DEVICES,
    CONF_LLM_BLOCK_ENTITIES,
    CONF_LLM_MODE,
    LlmMode,
    blocked_entity_checker,
    get_blocked_devices,
    get_blocked_entities,
)
from custom_components.ha_insights.const import DOMAIN
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)
from custom_components.ha_insights.ws_api._helpers import _resolve_blocked_entities


def _device(hass: HomeAssistant, uid: str, via: str | None = None) -> tuple[str, str]:
    """Register a device with one sensor; return (device_id, entity_id)."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        via_device=("test", via) if via else None,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_power", device_id=device.id, config_entry=source
    )
    return device.id, ent.entity_id


def _add_entity(hass: HomeAssistant, device_id: str, uid: str) -> str:
    return (
        er.async_get(hass)
        .async_get_or_create("sensor", "test", uid, device_id=device_id)
        .entity_id
    )


def _entry(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_LLM_MODE: LlmMode.OFF.value}, options=options
    )
    entry.add_to_hass(hass)
    return entry


def _event(entity_id: str) -> StateEvent:
    return StateEvent(
        timestamp=datetime.now(tz=UTC),
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        area_id=None,
        old_state="1",
        new_state="2",
    )


# --- getters -----------------------------------------------------------------


async def test_get_blocked_devices_normalizes(hass: HomeAssistant) -> None:
    assert get_blocked_devices(_entry(hass)) == frozenset()
    entry = _entry(hass, **{CONF_BLOCKED_DEVICES: [" abc ", "", "def"]})
    assert get_blocked_devices(entry) == frozenset({"abc", "def"})
    assert get_blocked_devices(_entry(hass, **{CONF_BLOCKED_DEVICES: "abc"})) == frozenset()


async def test_blocked_entities_include_device_entities_with_hass(
    hass: HomeAssistant,
) -> None:
    dev, dev_sensor = _device(hass, "emporia")
    _, other_sensor = _device(hass, "other")
    entry = _entry(
        hass,
        **{CONF_BLOCKED_DEVICES: [dev], CONF_LLM_BLOCK_ENTITIES: ["light.porch"]},
    )
    # Without hass: explicit list only (old behavior for old call sites).
    assert get_blocked_entities(entry) == frozenset({"light.porch"})
    blocked = get_blocked_entities(entry, hass)
    assert blocked == frozenset({"light.porch", dev_sensor})
    assert other_sensor not in blocked


async def test_blocked_device_covers_entities_added_later_and_disabled(
    hass: HomeAssistant,
) -> None:
    dev, _ = _device(hass, "emporia")
    entry = _entry(hass, **{CONF_BLOCKED_DEVICES: [dev]})
    later = _add_entity(hass, dev, "emporia_port_16")
    disabled = _add_entity(hass, dev, "emporia_port_9")
    er.async_get(hass).async_update_entity(
        disabled, disabled_by=er.RegistryEntryDisabler.USER
    )
    blocked = get_blocked_entities(entry, hass)
    assert later in blocked
    assert disabled in blocked


async def test_device_behind_blocked_hub_is_not_blocked(hass: HomeAssistant) -> None:
    hub, hub_sensor = _device(hass, "hub")
    _, child_sensor = _device(hass, "child", via="hub")
    entry = _entry(hass, **{CONF_BLOCKED_DEVICES: [hub]})
    blocked = get_blocked_entities(entry, hass)
    assert hub_sensor in blocked
    assert child_sensor not in blocked


async def test_ws_resolver_includes_device_entities(hass: HomeAssistant) -> None:
    dev, dev_sensor = _device(hass, "emporia")
    _entry(hass, **{CONF_BLOCKED_DEVICES: [dev]})
    assert dev_sensor in _resolve_blocked_entities(hass, get_blocked_entities)


# --- buffer ------------------------------------------------------------------


async def test_checker_is_none_when_nothing_blocked(hass: HomeAssistant) -> None:
    assert blocked_entity_checker(hass, _entry(hass)) is None


async def test_buffer_drops_blocked_entities_and_device_entities(
    hass: HomeAssistant,
) -> None:
    dev, dev_sensor = _device(hass, "emporia")
    _, other_sensor = _device(hass, "other")
    entry = _entry(
        hass,
        **{CONF_BLOCKED_DEVICES: [dev], CONF_LLM_BLOCK_ENTITIES: ["light.porch"]},
    )
    buffer_ = StateEventBuffer(is_blocked=blocked_entity_checker(hass, entry))
    # Added to the blocked device after the buffer was built.
    later = _add_entity(hass, dev, "emporia_port_16")

    assert buffer_.add(_event(dev_sensor)) is False
    assert buffer_.add(_event(later)) is False
    assert buffer_.add(_event("light.porch")) is False
    assert buffer_.add(_event(other_sensor)) is True
    # Not in the entity registry at all: kept.
    assert buffer_.add(_event("sensor.yaml_only")) is True
    assert [e.entity_id for e in buffer_.snapshot()] == [
        other_sensor,
        "sensor.yaml_only",
    ]


async def test_buffer_without_checker_keeps_everything() -> None:
    buffer_ = StateEventBuffer()
    assert buffer_.add(_event("sensor.anything")) is True
    assert len(buffer_) == 1


# --- options flow ------------------------------------------------------------


async def test_advanced_options_store_both_blocklists(hass: HomeAssistant) -> None:
    dev, _ = _device(hass, "emporia")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LLM_MODE: LlmMode.OFF.value},
        options={"analytics_install_uuid": "keep-me"},
        title="HA Insights",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "advanced"}
    )
    assert result["step_id"] == "advanced"
    schema_keys = {str(k) for k in result["data_schema"].schema}
    assert {CONF_LLM_BLOCK_ENTITIES, CONF_BLOCKED_DEVICES} <= schema_keys

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_LLM_MODE: LlmMode.OFF.value,
            CONF_LLM_BLOCK_ENTITIES: ["light.porch", "light.porch"],
            CONF_BLOCKED_DEVICES: [dev],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LLM_BLOCK_ENTITIES] == ["light.porch"]
    assert result["data"][CONF_BLOCKED_DEVICES] == [dev]
    assert result["data"]["analytics_install_uuid"] == "keep-me"


async def test_advanced_options_keep_blocklists_when_not_submitted(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LLM_MODE: LlmMode.OFF.value},
        options={
            CONF_LLM_BLOCK_ENTITIES: ["light.porch"],
            CONF_BLOCKED_DEVICES: ["dev1"],
        },
        title="HA Insights",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "advanced"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_LLM_MODE: LlmMode.OFF.value}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LLM_BLOCK_ENTITIES] == ["light.porch"]
    assert result["data"][CONF_BLOCKED_DEVICES] == ["dev1"]
