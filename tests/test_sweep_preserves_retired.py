"""The end-of-scan sweep must keep retired insights.

Retire is the user's permanent "don't suggest this" decision. The sweep
deletes active insights a detector didn't re-emit, and used to protect
only applied / dismissed / snoozed rows. A retired row was deleted the
first scan its detector skipped it, so the next detection inserted a
fresh row with no `retired_at` and notified the user again.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.ha_insights.insight import Insight, InsightKind
from custom_components.ha_insights.store import InsightStore


def _insight(insight_id: str) -> Insight:
    return Insight(
        id=insight_id,
        kind=InsightKind.AUTOMATION_IMPROVEMENT,
        detector="automation_audit",
        area_id=None,
        title=f"Audit {insight_id}",
        confidence=0.8,
        fingerprint={"automation_id": insight_id, "kind": "automation_audit"},
        payload={},
        payload_format="report",
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[InsightStore]:
    db = InsightStore(tmp_path / "test.db")
    await db.open()
    yield db
    await db.close()


async def test_sweep_keeps_retired_and_deletes_plain_stale(store: InsightStore) -> None:
    for iid in ("retired", "stale"):
        await store.add_insight(_insight(iid))
    await store.retire_insight("retired")

    swept = await store.replace_active_insights_for_detectors(
        completed_detectors=frozenset({"automation_audit"}),
        emitted_ids=frozenset(),
    )

    assert swept == 1
    assert await store.get_insight("stale") is None
    kept = await store.get_insight("retired")
    assert kept is not None
    assert kept.retired_at is not None


async def test_retired_stays_retired_after_skip_then_redetect(store: InsightStore) -> None:
    await store.add_insight(_insight("a"))
    await store.retire_insight("a")
    # One scan where the detector ran but didn't flag this automation.
    await store.replace_active_insights_for_detectors(
        completed_detectors=frozenset({"automation_audit"}),
        emitted_ids=frozenset(),
    )
    # Flagged again next scan.
    await store.add_insight(_insight("a"))

    assert await store.list_insights() == []
    retired = await store.list_insights(include_retired=True)
    assert [i.id for i in retired] == ["a"]
