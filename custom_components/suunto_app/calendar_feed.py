"""A subscribable calendar feed (.ics) of the workouts, per account.

`GET /api/suunto_app/calendar/<token>.ics` answers with an iCalendar file
anyone with the link can add to their phone or Google Calendar - a coach or a
partner, without a Home Assistant account. It holds the workouts of the last
90 days with the same text as the workouts calendar entity (sport, distance,
duration, heart rate, TSS, PTE). Never the start position, the sleep, the
readiness or anything else.

Only while "Calendar link for others" is on under Configure. The token is a
random 32-byte secret in the entry's data (CONF_CALENDAR_FEED_TOKEN): no
login, so the link itself is the key. Turning the option off removes the
token (the link answers 404); turning it on again makes a new one.

Built from the workouts the integration already holds - no request to Suunto,
so a phone checking the feed every hour never makes it fetch anything.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.calendar import CalendarEvent
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import CONF_CALENDAR_FEED_ENABLED, CONF_CALENDAR_FEED_TOKEN, DOMAIN

URL = f"/api/{DOMAIN}/calendar/{{token}}"
_SUFFIX = ".ics"
_VIEW_REGISTERED = f"{DOMAIN}_calendar_feed_view"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def feed_path(token: str) -> str:
    return f"/api/{DOMAIN}/calendar/{token}{_SUFFIX}"


def feed_url(hass: HomeAssistant, token: str) -> str:
    """The full link: the external address when Home Assistant has one (a
    phone outside the home network needs it), else the internal one."""
    try:
        base = get_url(hass, allow_internal=False, prefer_external=True)
    except NoURLAvailableError:
        try:
            base = get_url(hass)
        except NoURLAvailableError:
            base = ""
    return f"{base}{feed_path(token)}"


# --- the events (shared with the workouts calendar entity) -----------------


def workout_events(workouts: list[dict[str, Any]]) -> list[CalendarEvent]:
    """A CalendarEvent per normalized workout, for the workouts calendar
    entity (calendar.py) and this feed, so both show the same text. No location: the start
    position stays out of the calendar."""
    events: list[CalendarEvent] = []
    for w in workouts:
        start = w.get("start_time")
        if not isinstance(start, datetime):
            continue
        minutes = w.get("duration_minutes") or 0
        end = start + timedelta(minutes=minutes or 1)
        distance = w.get("distance_meters")
        km = f"{distance / 1000:.1f} km" if distance else None
        summary = " - ".join(p for p in (w.get("activity") or "Workout", km) if p)
        details = []
        if minutes:
            details.append(f"{minutes} min")
        if w.get("avg_hr_bpm"):
            details.append(f"HR {w['avg_hr_bpm']}/{w.get('max_hr_bpm') or '?'} bpm")
        if w.get("tss"):
            details.append(f"TSS {w['tss']}")
        # Suunto's own 1..5 session-impact rating, alongside the derived TSS.
        if w.get("pte"):
            details.append(f"PTE {w['pte']}")
        events.append(
            CalendarEvent(
                start=start,
                end=end,
                summary=summary,
                description=" - ".join(details) or None,
                uid=w.get("key"),
            )
        )
    return events


# --- iCalendar text -------------------------------------------------------


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Lines longer than 75 octets go on in a continuation line starting
    with a space (RFC 5545 3.1), never splitting a UTF-8 character."""
    out: list[str] = []
    current = ""
    size = 0
    for char in line:
        width = len(char.encode("utf-8"))
        limit = 75 if not out else 74
        if size + width > limit:
            out.append(current)
            current, size = "", 0
        current += char
        size += width
    out.append(current)
    return "\r\n ".join(out)


def _when(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return ":" + dt_util.as_utc(value).strftime("%Y%m%dT%H%M%SZ")
    return ";VALUE=DATE:" + value.strftime("%Y%m%d")


def _uid(event: CalendarEvent) -> str:
    if event.uid:
        return f"{event.uid}@{DOMAIN}"
    raw = f"{event.start}|{event.summary}"
    return f"workout-{hashlib.sha1(raw.encode()).hexdigest()[:16]}@{DOMAIN}"


def build_ics(name: str, events: Iterable[CalendarEvent], now: datetime) -> str:
    """The whole .ics text."""
    stamp = dt_util.as_utc(now).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Suunto App (unofficial)//Home Assistant//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for event in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_uid(event)}",
            f"DTSTAMP:{stamp}",
            f"DTSTART{_when(event.start)}",
            f"DTEND{_when(event.end)}",
            f"SUMMARY:{_escape(event.summary or '')}",
        ]
        if event.description:
            lines.append(f"DESCRIPTION:{_escape(event.description)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


# --- the feed --------------------------------------------------------------


def _feed_name(hass: HomeAssistant, entry) -> str:
    """The device name as the user sees it (renamed or not)."""
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if (DOMAIN, entry.entry_id) in device.identifiers and (
            device.name_by_user or device.name
        ):
            return device.name_by_user or device.name
    return entry.title


def _entry_for_token(hass: HomeAssistant, token: str):
    for entry in hass.config_entries.async_entries(DOMAIN):
        stored = entry.data.get(CONF_CALENDAR_FEED_TOKEN)
        if (
            stored
            and secrets.compare_digest(str(stored), token)
            and entry.options.get(CONF_CALENDAR_FEED_ENABLED)
            and entry.state is ConfigEntryState.LOADED
        ):
            return entry
    return None


class SuuntoCalendarFeedView(HomeAssistantView):
    """The .ics feed. No Home Assistant login: the token in the link is the
    key, and an unknown or switched-off one gets a plain 404."""

    url = URL
    name = f"api:{DOMAIN}:calendar_feed"
    requires_auth = False

    async def get(self, request: web.Request, token: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        token = token.removesuffix(_SUFFIX)
        entry = _entry_for_token(hass, token) if token else None
        if entry is None:
            return web.Response(status=HTTPStatus.NOT_FOUND, text="Not found")
        workouts = (entry.runtime_data.daily.data or {}).get("workouts") or []
        body = build_ics(_feed_name(hass, entry), workout_events(workouts), dt_util.now())
        return web.Response(
            text=body,
            content_type="text/calendar",
            charset="utf-8",
            headers={
                "Content-Disposition": 'inline; filename="suunto.ics"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )


def async_register_calendar_feed_view(hass: HomeAssistant) -> None:
    """Once per Home Assistant run (views can't be unregistered)."""
    if hass.data.get(_VIEW_REGISTERED):
        return
    hass.http.register_view(SuuntoCalendarFeedView())
    hass.data[_VIEW_REGISTERED] = True
