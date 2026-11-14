"""Receiver readback, service-ID decoding, and refresh scheduling."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from .const import (
    DOMAIN, SERVICES, CONF_HOST, CONF_PORT, DEFAULT_PORT,
    QUERY_GAP_SECONDS,
)
from .eiscp import send_command
from .receiver_data import ZONE_COMMANDS
from .extended import (
    AUDIO_FIELDS, VIDEO_FIELDS, EXTENDED_QUERIES, LEVEL_CONTROLS,
    decode_information, decode_level,
)

_LOGGER = logging.getLogger(__name__)

# Explicit source IDs derived from HT-R997 NMS status replies, including
# S1xx, S2xx, and 2xx markers. Do not parse the NSV prefix as a service ID.
SERVICE_BY_ID = {
    "0E": "TuneIn", "04": "Pandora", "0A": "Spotify", "12": "Deezer",
    "1B": "TIDAL", "1C": "Amazon Music", "43": "FlareConnect",
    "40": "Chromecast built-in", "42": "DTS Play-Fi", "18": "AirPlay",
    "00": "Music Server", "F0": "USB", "1D": "Play Queue",
}
assert set(SERVICE_BY_ID.values()) == set(SERVICES)


def decode_nms_service_id(response: str | None) -> str | None:
    """Find service ID in NMS...S10a, NMS...S2f0, NMS...20e, etc.

    Known S1/S2 and 2xx markers take precedence. Some older replies use a
    bare two-digit suffix, which is only accepted if it maps to a known ID.
    """
    if not response:
        return None
    payload = response.strip().removeprefix("!1")
    if not payload.upper().startswith("NMS"):
        return None
    tail = payload[3:].upper()
    match = re.search(r"S[12]([0-9A-F]{2})$", tail)
    if match:
        return match.group(1) if match.group(1) in SERVICE_BY_ID else None
    match = re.search(r"2([0-9A-F]{2})$", tail)
    if match:
        return match.group(1) if match.group(1) in SERVICE_BY_ID else None
    # Some device status variants omit the marker and end with only the ID.
    match = re.search(r"([0-9A-F]{2})$", tail)
    return match.group(1) if match and match.group(1) in SERVICE_BY_ID else None


async def async_read_nms(host: str, port: int, *, timeout: float = 3.0):
    """Discovery and connection checks use the same readback query path."""
    return await send_command(host, port, "NMSQSTN", timeout=timeout)


def decode_mute(response: str | None) -> str | None:
    value = (response or "").strip().removeprefix("!1").upper()
    if value.startswith("AMT01"):
        return "On"
    if value.startswith("AMT00"):
        return "Off"
    return None


def decode_volume(response: str | None) -> int | None:
    value = (response or "").strip().removeprefix("!1").upper()
    match = re.match(r"^MVL([0-9A-F]{2})(?:$|[^0-9A-F])", value)
    return int(match.group(1), 16) if match else None


# Tell only affected entities to refresh their displayed state. Stable
# values avoid redundant sensor updates; diagnostic timestamps still update.
def publish(hass, entry, changed):
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime:
        for entity in tuple(runtime["sync_entities"]):
            if "connected" in changed or changed.intersection(entity.sync_keys):
                entity.async_write_ha_state()


# All built-in query replies pass here: serialize network access, decode
# one response, update diagnostics, then notify dependent entities.
async def async_query(hass, entry, command: str):
    """Send a query and update one part of cached receiver state."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is None:
        return None
    error = None
    try:
        async with runtime["lock"]:
            response = await send_command(
                entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT),
                command, timeout=3.0, expect_response=True,
            )
    except (OSError, ValueError, asyncio.TimeoutError) as err:
        _LOGGER.debug("Receiver query %s failed: %s", command, err)
        response = None
        error = str(err)
    # Do not replace a previously known state with Unknown merely because a
    # single query timed out; mark initial state unavailable until first read.
    # Status describes this query, not a promise that every cached value is fresh.
    updates = {
        "last_query": command, "last_response": response,
        "query_error": error,
        "query_status": "Response received" if response else ("Query failed" if error else "No response"),
        "query_failures": 0 if response else runtime["query_failures"] + 1,
    }
    if response:
        updates["last_success"] = datetime.now(timezone.utc)
    if hass.data.get(DOMAIN, {}).get(entry.entry_id) is not runtime:
        return response
    if response:
        process_message(hass, entry, response)
    changed = {key for key, value in updates.items() if runtime[key] != value}
    if changed:
        runtime.update(updates)
        publish(hass, entry, changed)
    return response



def process_message(hass, entry, response):
    """Process push messages and query replies through one shared state cache."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is None:
        return
    command = response[:3]
    updates = {}
    if command in ("IFA", "IFV"):
        audio = command.startswith("IFA")
        parsed = decode_information(response, "IFA" if audio else "IFV",
                                    AUDIO_FIELDS if audio else VIDEO_FIELDS)
        if parsed is not None:
            updates["audio_info" if audio else "video_info"] = parsed
    elif command[:3] in LEVEL_CONTROLS:
        parsed = decode_level(response, command[:3])
        if parsed is not None:
            updates[LEVEL_CONTROLS[command[:3]][1]] = parsed
    elif command == "AMT":
        parsed = decode_mute(response)
        if parsed is not None:
            updates["mute_state"] = parsed
    elif command == "MVL":
        parsed = decode_volume(response)
        if parsed is not None:
            updates["volume"] = parsed
    elif command == "SLI":
        match = re.match(r"^SLI([0-9A-Fa-f]{2})", response)
        if match:
            updates["input_code"] = match.group(1).upper()
            updates["input_available"] = True
            # Preserve last NMS result but do not report it as current for non-NET.
    elif command == "NMS":
        updates["nms_response"] = response
        updates["service_id"] = decode_nms_service_id(response)
        updates["current_service"] = SERVICE_BY_ID.get(updates["service_id"])
    # Update every supported zone, not just the legacy main-zone sensors.
    for zone, codes in ZONE_COMMANDS.items():
        if zone not in runtime["zones"]:
            continue
        field = next((field for field, code in codes.items() if code == command), None)
        if field is None:
            continue
        body = response[3:]
        state = dict(runtime["zones"][zone])
        try:
            if field in ("power", "mute") and body in ("00", "01"):
                state[field] = body == "01"
            elif field == "volume" and re.fullmatch(r"[0-9A-Fa-f]{2}(?:[05])?",body):
                state[field] = int(body[:2],16) + (0.5 if body[2:] == "5" else 0)
            elif field == "preset" and re.fullmatch(r"[0-9A-Fa-f]{2}",body):
                state[field] = int(body,16)
            elif field in ("source", "mode") and re.fullmatch(r"[0-9A-Fa-f]{2}",body):
                state[field] = body.upper()
        except ValueError:
            pass
        if state != runtime["zones"][zone]:
            runtime["zones"][zone] = state
            updates[f"zone_{zone}"] = state
    if command == "HDO" and re.fullmatch(r"[0-9A-Fa-f]{2}", response[3:]):
        updates["hdmi_output"] = response[3:].upper()
    if command == "CMT" and re.fullmatch(r"(?:00|01){13}", response[3:]):
        updates["channel_mutes"] = [response[i:i+2] == "01" for i in range(3,29,2)]
    changed = {key for key,value in updates.items() if runtime.get(key) != value}
    if changed:
        runtime.update(updates)
        publish(hass, entry, changed)

# Read back only the state associated with an action, and only when the
# owner has enabled post-action updates. Navigation needs no state query.
async def async_query_after_action(hass, entry, action_command: str):
    """Targeted readback after a button press, when enabled by the user."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not runtime or not runtime["update_after_input"]:
        return
    command = action_command.upper()
    # Let the action finish and its push acknowledgement arrive before asking
    # again. This avoids the stale immediate reads observed in live testing.
    await asyncio.sleep(0.5)
    if command[:3] in LEVEL_CONTROLS:
        await async_query(hass, entry, command[:3] + "QSTN")
    elif command.startswith("LMD"):
        await async_query(hass, entry, "LMDQSTN")
    elif command.startswith("AMT"):
        await async_query(hass, entry, "AMTQSTN")
    elif command.startswith("MVL"):
        await async_query(hass, entry, "MVLQSTN")
    elif command.startswith(("NSV", "SLI")):
        await async_query(hass, entry, "SLIQSTN")
        await async_query(hass, entry, "NMSQSTN")


# Full refreshes use a fixed order and ten-second gaps. The same worker
# handles startup, manual refresh and periodic polling, preventing overlap.
async def async_refresh(hass, entry, *, extended_only=False):
    """One full refresh, serial queries 10 s apart; skip overlapping runs."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is None or runtime["refresh_lock"].locked():
        return
    async with runtime["refresh_lock"]:
        # SLI first ensures network-service display is interpreted against the
        # current receiver input. Always query NMS as requested, even off NET.
        # Optional queries add 40 seconds to a normal batch. Off by default,
        # they can also be requested with the extended-information button.
        queries = EXTENDED_QUERIES if extended_only else (
            "SLIQSTN", "NMSQSTN", "MVLQSTN", "AMTQSTN")
        if not extended_only and runtime["include_extended"]:
            queries += EXTENDED_QUERIES
        for i, command in enumerate(queries):
            if i:
                await asyncio.sleep(QUERY_GAP_SECONDS)
            if hass.data.get(DOMAIN, {}).get(entry.entry_id) is not runtime:
                return
            await async_query(hass, entry, command)
        # Completion means every query was attempted, even if one timed out.
        runtime["last_refresh"] = datetime.now(timezone.utc)
        publish(hass, entry, {"last_refresh"})


def schedule_refresh(hass, entry, *, extended_only=False):
    """Start manual/initial refresh without blocking button services for ~30s."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is None:
        return
    task = runtime.get("refresh_task")
    if task is not None and not task.done():
        if extended_only:
            runtime["extended_pending"] = True
        return
    runtime["refresh_task"] = entry.async_create_background_task(
        hass, _refresh_worker(hass, entry, runtime, extended_only), "Onkyo Extended refresh")


async def _refresh_worker(hass, entry, runtime, extended_only):
    """Run one batch, then honour a coalesced extended refresh request."""
    await async_refresh(hass, entry, extended_only=extended_only)
    while runtime.pop("extended_pending", False):
        if hass.data.get(DOMAIN, {}).get(entry.entry_id) is not runtime:
            return
        await async_refresh(hass, entry, extended_only=True)
