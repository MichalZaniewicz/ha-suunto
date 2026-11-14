"""Copy workouts into another calendar - the `suunto_app.sync_calendar` action.

The workouts go into a calendar of your choice (Google Calendar, a Local
Calendar), with the same text as the workouts calendar entity, so they show
up wherever that calendar does. Every copy carries a tag at the end of its
description:

    [suunto-sync:3f9a1c:6531a2b8e4b0c1d2e3f4a5b6]

(account, workout). That keeps the copies in step with Suunto: a workout
edited in the app is rewritten, one deleted there is removed, and nothing
without our tag - events added by hand, or another account's - is ever
touched. Two accounts can share one calendar.

Only the last `days` days are looked at (the workouts the integration holds,
at most 90). Nothing is fetched from Suunto. One run at a time per (target
calendar, account), so a run started twice never adds a workout twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.components.calendar import CalendarEntityFeature, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from .calendar_feed import workout_events
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_TAG_RE = re.compile(r"\[suunto-sync:([0-9a-f]{6}):([A-Za-z0-9_.:-]+)\]")

_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


@dataclass(frozen=True, slots=True)
class SyncItem:
    """One workout as it should look in the target calendar."""

    key: str
    summary: str
    start: datetime
    end: datetime
    description: str  # without the tag

    def tagged_description(self, account: str) -> str:
        tag = f"[suunto-sync:{account}:{self.key}]"
        return f"{self.description}\n\n{tag}" if self.description else tag


def account_tag(entry_id: str) -> str:
    """Six hex characters per config entry: enough to tell accounts apart."""
    return hashlib.sha1(entry_id.encode()).hexdigest()[:6]


def parse_sports(value: str | list[str] | None) -> list[str]:
    """"Cycling, running" or a list -> lowercased names; empty = every sport."""
    if not value:
        return []
    parts = value.split(",") if isinstance(value, str) else [p for v in value for p in str(v).split(",")]
    return [p.strip().casefold() for p in parts if p.strip()]


def sync_items(
    workouts: list[dict[str, Any]],
    *,
    since: datetime,
    sports: list[str],
    prefix: str = "",
) -> list[SyncItem]:
    """The copies the target calendar should hold: every workout that
    started at or after ``since``, of one of ``sports`` (all when empty)."""
    head = f"{prefix.strip()} " if prefix and prefix.strip() else ""
    by_key = {w.get("key"): w for w in workouts if w.get("key")}
    items: list[SyncItem] = []
    for event in workout_events(list(by_key.values())):
        if not event.uid or event.start < since:
            continue
        sport = (by_key[event.uid].get("activity") or "").casefold()
        if sports and sport not in sports:
            continue
        items.append(
            SyncItem(
                key=event.uid,
                summary=f"{head}{event.summary}",
                start=event.start,
                end=event.end,
                description=(event.description or "").strip(),
            )
        )
    return sorted(items, key=lambda item: item.start)


def _strip_tag(description: str | None) -> str:
    return _TAG_RE.sub("", description or "").strip()


def _same(item: SyncItem, event: CalendarEvent) -> bool:
    if not isinstance(event.start, datetime) or not isinstance(event.end, datetime):
        return False
    return (
        event.summary == item.summary
        and dt_util.as_utc(event.start) == dt_util.as_utc(item.start)
        and dt_util.as_utc(event.end) == dt_util.as_utc(item.end)
        and " ".join(_strip_tag(event.description).split()) == " ".join(item.description.split())
    )


def _event_fields(item: SyncItem, account: str) -> dict[str, Any]:
    return {
        "summary": item.summary,
        "dtstart": item.start,
        "dtend": item.end,
        "description": item.tagged_description(account),
    }


async def async_sync_calendar(
    hass: HomeAssistant,
    *,
    entry_id: str,
    target_entity_id: str,
    items: list[SyncItem],
    since: datetime,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Bring ``target_entity_id`` in line with ``items`` from ``since`` on.
    Returns counts (with ``dry_run`` also the planned changes, none made)."""
    component = hass.data.get("calendar")
    entity = component.get_entity(target_entity_id) if component is not None else None
    if entity is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="sync_bad_calendar",
            translation_placeholders={"entity_id": target_entity_id},
        )
    features = entity.supported_features or 0
    if not features & CalendarEntityFeature.CREATE_EVENT:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="sync_read_only_calendar",
            translation_placeholders={"entity_id": target_entity_id},
        )
    can_update = bool(features & CalendarEntityFeature.UPDATE_EVENT)
    can_delete = bool(features & CalendarEntityFeature.DELETE_EVENT)
    account = account_tag(entry_id)

    lock = _LOCKS.setdefault((target_entity_id, entry_id), asyncio.Lock())
    async with lock:
        existing = await entity.async_get_events(
            hass, since, dt_util.now() + timedelta(days=1)
        )
        ours: dict[str, list[CalendarEvent]] = {}
        for event in existing:
            match = _TAG_RE.search(event.description or "")
            if match is not None and match.group(1) == account:
                ours.setdefault(match.group(2), []).append(event)

        created = updated = deleted = unchanged = not_removable = errors = 0
        planned: list[dict[str, Any]] = []

        async def run(action: str, call: Callable[[], Awaitable[Any]], summary: str) -> bool:
            nonlocal errors
            planned.append({"action": action, "summary": summary})
            if dry_run:
                return True
            try:
                await call()
            except (HomeAssistantError, ValueError) as err:
                errors += 1
                _LOGGER.warning(
                    "Calendar sync to %s: could not %s %r: %s",
                    target_entity_id, action, summary, err,
                )
                return False
            return True

        async def remove(event: CalendarEvent) -> None:
            nonlocal deleted, not_removable
            if not can_delete or not event.uid:
                not_removable += 1
                return
            if await run("delete", partial(entity.async_delete_event, event.uid), event.summary):
                deleted += 1

        async def create(item: SyncItem) -> None:
            nonlocal created
            fields = _event_fields(item, account)
            if await run("create", partial(entity.async_create_event, **fields), item.summary):
                created += 1

        for item in items:
            matches = ours.pop(item.key, [])
            current, extra = (matches[0], matches[1:]) if matches else (None, [])
            for duplicate in extra:
                await remove(duplicate)
            if current is None:
                await create(item)
            elif _same(item, current):
                unchanged += 1
            elif can_update and current.uid:
                fields = _event_fields(item, account)
                if await run(
                    "update", partial(entity.async_update_event, current.uid, fields), item.summary
                ):
                    updated += 1
            else:
                # Google Calendar allows only adding and deleting.
                await remove(current)
                await create(item)

        # Tagged for this account but gone from Suunto (deleted, or a sport
        # no longer copied). Copies older than the window are left alone.
        for leftovers in ours.values():
            for event in leftovers:
                await remove(event)

    result: dict[str, Any] = {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "unchanged": unchanged,
        "not_removable": not_removable,
        "errors": errors,
    }
    if dry_run:
        result["planned"] = planned
    return result
