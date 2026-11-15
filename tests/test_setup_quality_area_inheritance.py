"""setup_quality area checks must count areas inherited from devices.

HA resolves an entity's area as its own `area_id` if set, otherwise its
device's. Entities created by integrations almost always inherit, so
checking only the entity's own `area_id` reports a fully-assigned home
as having no area coverage.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.setup_quality import (
    _MOTION_CLASSES,
    _device_class_areas,
    _has_area_coverage,
)


async def _motion_entity_in_device_area(
    hass: HomeAssistant, area_name: str, uid: str
) -> str:
    """A motion sensor whose area comes only from its device."""
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    area = ar.async_get(hass).async_create(area_name)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test", uid)},
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    ent = er.async_get(hass).async_get_or_create(
        "binary_sensor", "test", uid, device_id=device.id, config_entry=entry
    )
    assert ent.area_id is None
    hass.states.async_set(ent.entity_id, "off", {"device_class": "motion"})
    return area.id


async def test_area_coverage_counts_device_inherited_areas(hass: HomeAssistant) -> None:
    await _motion_entity_in_device_area(hass, "Garage", "garage_motion")
    ok, detail = _has_area_coverage(DetectorContext(hass=hass))
    assert ok is True
    assert detail.startswith("1/1 entities (100%) tagged")


async def test_entity_own_area_overrides_device_area(hass: HomeAssistant) -> None:
    await _motion_entity_in_device_area(hass, "Garage", "garage_motion")
    kitchen = ar.async_get(hass).async_create("Kitchen")
    e_reg = er.async_get(hass)
    ent = next(iter(e_reg.entities.values()))
    e_reg.async_update_entity(ent.entity_id, area_id=kitchen.id)
    have, total = _device_class_areas(DetectorContext(hass=hass), _MOTION_CLASSES)
    assert (have, total) == (1, 2)


async def test_motion_coverage_counts_device_inherited_areas(hass: HomeAssistant) -> None:
    await _motion_entity_in_device_area(hass, "Garage", "garage_motion")
    ar.async_get(hass).async_create("Attic")
    have, total = _device_class_areas(DetectorContext(hass=hass), _MOTION_CLASSES)
    assert (have, total) == (1, 2)


async def test_entity_without_any_area_still_uncounted(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "binary_sensor", "test", "loose", config_entry=entry
    )
    ok, detail = _has_area_coverage(DetectorContext(hass=hass))
    assert ok is False
    assert detail.startswith("0/1 entities")
