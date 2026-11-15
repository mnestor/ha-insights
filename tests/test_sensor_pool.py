"""Sensor events live in their own capped pool.

Chatty `sensor.*` entities (BLE distances, power metering) used to share
the 500k cap with everything else. Backfill inserts entity by entity, so
once the cap engaged each new sensor reading evicted the oldest entity's
whole multi-day history. Sensor events must now only evict other sensor
events, and sensor-pool events older than its max age are dropped.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _ev(entity_id: str, minutes: float = 0.0, state: str = "1") -> StateEvent:
    return StateEvent(
        timestamp=T0 + timedelta(minutes=minutes),
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        area_id=None,
        old_state=None,
        new_state=state,
    )


def test_sensor_flood_does_not_evict_other_history() -> None:
    buf = StateEventBuffer(max_events=5, sensor_max_events=3)
    for i in range(5):
        buf.add(_ev("light.kitchen", minutes=i))
    for i in range(10):
        assert buf.add(_ev("sensor.phone_distance", minutes=10 + i)) is True
    lights = [e for e in buf.snapshot() if e.domain == "light"]
    sensors = [e for e in buf.snapshot() if e.domain == "sensor"]
    assert len(lights) == 5
    assert [e.timestamp for e in sensors] == [
        T0 + timedelta(minutes=m) for m in (17, 18, 19)
    ]
    assert len(buf) == 8
    assert buf.sensor_event_count == 3


def test_main_cap_still_applies_to_non_sensor_events() -> None:
    buf = StateEventBuffer(max_events=3, sensor_max_events=10)
    for i in range(5):
        buf.add(_ev("switch.fan", minutes=i))
    assert [e.timestamp.minute for e in buf.snapshot()] == [2, 3, 4]


def test_sensor_pool_ages_out_old_events() -> None:
    buf = StateEventBuffer(sensor_max_age=timedelta(hours=48))
    buf.add(_ev("sensor.power", minutes=0))
    buf.add(_ev("sensor.power", minutes=60))
    buf.add(_ev("sensor.power", minutes=49 * 60))
    assert [e.timestamp for e in buf.snapshot()] == [
        T0 + timedelta(minutes=60),
        T0 + timedelta(minutes=49 * 60),
    ]


def test_query_snapshot_and_span_cover_both_pools() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    buf.add(_ev("binary_sensor.door", minutes=0))
    buf.add(_ev("sensor.power", minutes=5))
    assert {e.entity_id for e in buf.query()} == {"binary_sensor.door", "sensor.power"}
    assert [e.entity_id for e in buf.query(entity_id="sensor.power")] == ["sensor.power"]
    assert len(buf.snapshot()) == 2
    # Span comes from the oldest event in either pool (the door event).
    expected = (datetime.now(tz=UTC) - T0).total_seconds() / 86400.0
    assert abs(buf.data_span_days() - expected) < 0.01

    sensor_only = StateEventBuffer()
    sensor_only.add(_ev("sensor.power", minutes=5))
    assert sensor_only.data_span_days() > 0


def test_rename_covers_sensor_pool_and_keeps_caps() -> None:
    buf = StateEventBuffer(max_events=2, sensor_max_events=2)
    buf.add(_ev("sensor.old", minutes=0))
    buf.add(_ev("light.old", minutes=1))
    assert buf.rename_entity("sensor.old", "sensor.new") == 1
    assert buf.rename_entity("light.old", "light.new") == 1
    assert {e.entity_id for e in buf.snapshot()} == {"sensor.new", "light.new"}
    # Caps survive the rebuild.
    for i in range(5):
        buf.add(_ev("sensor.new", minutes=10 + i))
        buf.add(_ev("light.new", minutes=10 + i))
    assert buf.sensor_event_count == 2
    assert len(buf) == 4


def test_clear_and_prune_cover_sensor_pool() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=7), sensor_max_age=timedelta(hours=1))
    buf.add(_ev("sensor.power", minutes=0))
    buf.add(_ev("sensor.power", minutes=30))
    buf.add(_ev("light.kitchen", minutes=30))
    assert buf.prune(now=T0 + timedelta(minutes=75)) == 1
    assert len(buf) == 2
    assert buf.clear() == 2
    assert len(buf) == 0


def test_blocked_sensor_never_enters_pool() -> None:
    buf = StateEventBuffer(is_blocked=lambda eid: eid == "sensor.emporia_power")
    assert buf.add(_ev("sensor.emporia_power")) is False
    assert buf.sensor_event_count == 0
