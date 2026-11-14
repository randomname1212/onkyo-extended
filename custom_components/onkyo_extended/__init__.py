"""Onkyo Extended: standalone receiver control with one shared connection."""
from __future__ import annotations

import asyncio
import logging
import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN, PLATFORMS, CONF_HOST, CONF_PORT, CONF_CUSTOM_YAML,
    CONF_SHOW_HIDDEN, CONF_VISIBLE_SERVICES, CONF_EXTENDED_REFRESH,
    CONF_UPDATE_AFTER_INPUT, CONF_UPDATE_PERIOD_MINUTES,
    DEFAULT_UPDATE_PERIOD_MINUTES, SERVICES, HIDDEN_BY_DEFAULT,
)
from .eiscp import send_command, CLIENTS
from .connection import ReceiverConnection
from .receiver_data import decode_capabilities, initial_zone_states
from .sync import schedule_refresh, async_query_after_action, process_message, publish

_LOGGER = logging.getLogger(__name__)


# Saved options take precedence over the original setup values. This keeps
# existing installations working when new settings are introduced.
def get_setting(entry: ConfigEntry, key: str, default=None):
    return entry.options.get(key, entry.data.get(key, default))


# User YAML creates extra entities. Validate its structure once during setup
# so bad configuration fails with a useful message instead of a later crash.
def parse_custom_commands(entry: ConfigEntry) -> list[dict]:
    raw = get_setting(entry, CONF_CUSTOM_YAML, "") or ""
    if not raw.strip():
        return []
    try:
        data = yaml.safe_load(raw) or []
    except yaml.YAMLError as err:
        raise HomeAssistantError(f"Custom command YAML is invalid: {err}") from err
    if not isinstance(data, list):
        raise HomeAssistantError("Custom commands YAML must be a list.")
    allowed_types = {"button", "switch", "select", "sensor"}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise HomeAssistantError(f"Custom command {index + 1} must be a YAML object.")
        for required in ("name", "type", "command"):
            if not item.get(required):
                raise HomeAssistantError(f"Custom command {index + 1} is missing {required!r}.")
        if item["type"] not in allowed_types:
            raise HomeAssistantError(f"Unsupported entity type: {item['type']}")
        if not isinstance(item["command"], str):
            raise HomeAssistantError("Each command must be a string.")
    return data


def initial_visible_services(entry):
    saved = get_setting(entry, CONF_VISIBLE_SERVICES, {}) or {}
    all_visible = bool(get_setting(entry, CONF_SHOW_HIDDEN, False))
    return {name: bool(saved.get(name, all_visible or name not in HIDDEN_BY_DEFAULT))
            for name in SERVICES}


# This is the only periodic scheduler. A timer of zero waits for a settings
# change; shorter intervals never create overlapping full refresh batches.
async def _periodic_loop(hass, entry, runtime):
    """Interval is start-to-start, bounded by duration of a refresh batch."""
    loop = asyncio.get_running_loop()
    while hass.data.get(DOMAIN, {}).get(entry.entry_id) is runtime:
        minutes = runtime["period_minutes"]
        if minutes <= 0:
            await runtime["timer_changed"].wait()
            runtime["timer_changed"].clear()
            runtime["next_poll"] = loop.time() + runtime["period_minutes"] * 60
            continue
        delay = max(0, runtime["next_poll"] - loop.time())
        try:
            await asyncio.wait_for(runtime["timer_changed"].wait(), timeout=delay)
            runtime["timer_changed"].clear()
            runtime["next_poll"] = loop.time() + runtime["period_minutes"] * 60
            continue
        except asyncio.TimeoutError:
            runtime["next_poll"] = loop.time() + minutes * 60
            schedule_refresh(hass, entry)
            # Finish the active batch before checking the next deadline. This
            # avoids skipping alternate ticks at 0.5 min when a batch takes
            # slightly more than 30 seconds. Full refreshes never overlap.
            task = runtime.get("refresh_task")
            if task is not None:
                await asyncio.shield(task)


# Create the shared cache, locks and entity lists, then load the platforms.
# Each receiver has a separate runtime identified by its config-entry ID.
async def async_setup(hass, config):
    """Serve the packaged dashboard card once, using HA's async HTTP API."""
    from pathlib import Path
    from homeassistant.components.http import StaticPathConfig
    await hass.http.async_register_static_paths([StaticPathConfig(
        "/onkyo_extended/choice-card.js",
        str(Path(__file__).parent / "frontend" / "choice-card.js"), False)])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    commands = parse_custom_commands(entry)
    host, port = entry.data[CONF_HOST], entry.data.get(CONF_PORT, 60128)
    client = ReceiverConnection(host, port,
        lambda coro, name: entry.async_create_background_task(hass, coro, name))
    CLIENTS[(host, port)] = client
    client.start()
    try:
        response = await send_command(host, port, "NRIQSTN", timeout=8)
        capabilities = decode_capabilities(response)
    except (OSError, ValueError, TimeoutError) as err:
        await client.close()
        CLIENTS.pop((host, port), None)
        raise ConfigEntryNotReady(str(err)) from err
    runtime = {
        "lock": asyncio.Lock(), "refresh_lock": asyncio.Lock(),
        "client": client, "connected": client.connected,
        "capabilities": capabilities, "zones": initial_zone_states(capabilities),
        "channel_mutes": None, "hdmi_output": None,
        "commands": commands, "visible_services": initial_visible_services(entry),
        "select_entities": [], "sync_entities": [], "visibility_entities": [],
        "number_entities": [],
        "input_code": None, "input_available": False,
        "nms_response": None, "service_id": None, "current_service": None,
        "mute_state": None, "volume": None,
        # Optional information is unknown until a manual or enabled periodic read.
        "audio_info": {}, "video_info": {}, "centre_level": None, "subwoofer_level": None,
        "include_extended": bool(get_setting(entry, CONF_EXTENDED_REFRESH, False)),
        # A failed query does not erase old readings; these diagnostics show age.
        "query_status": "Not queried", "last_success": None, "last_refresh": None,
        "query_failures": 0, "last_query": None, "last_response": None, "query_error": None,
        "update_after_input": bool(get_setting(entry, CONF_UPDATE_AFTER_INPUT, True)),
        "period_minutes": max(0.0, min(60.0, round(float(get_setting(entry, CONF_UPDATE_PERIOD_MINUTES, DEFAULT_UPDATE_PERIOD_MINUTES)), 1))),
        "timer_changed": asyncio.Event(), "options_snapshot": dict(entry.options),
        "refresh_task": None,
    }
    runtime["next_poll"] = asyncio.get_running_loop().time() + runtime["period_minutes"] * 60
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if device and device.name and device.name.startswith(("Onkyo Extended", "Onkyo Extended")):
        registry.async_update_device(device.id, name=f"Onkyo Extended ({host})")
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await client.close()
        CLIENTS.pop((host, port), None)
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    # Background tasks must not be included in Home Assistant's startup wait.
    client.on_message = lambda message: process_message(hass, entry, message)
    def connection_changed(connected):
        runtime["connected"] = connected
        publish(hass, entry, {"connected"})
        if connected:
            task = runtime.get("bootstrap_task")
            if task is None or task.done():
                runtime["bootstrap_task"] = entry.async_create_background_task(
                    hass, _bootstrap_receiver(hass, entry, runtime), "Onkyo Extended reconnect state")
    client.on_connection = connection_changed
    runtime["periodic_task"] = entry.async_create_background_task(
        hass, _periodic_loop(hass, entry, runtime), "Onkyo Extended periodic refresh")
    runtime["bootstrap_task"] = entry.async_create_background_task(
        hass, _bootstrap_receiver(hass, entry, runtime), "Onkyo Extended initial state")

    async def async_send_command(call: ServiceCall) -> None:
        # Resolve the target at call time, so unloading one receiver cannot
        # leave the action pointing at an obsolete captured runtime.
        receivers = hass.data.get(DOMAIN, {})
        target_id = call.data.get("entry_id")
        if target_id is None:
            if len(receivers) != 1:
                raise HomeAssistantError("Specify entry_id when multiple receivers are configured")
            target_id = next(iter(receivers))
        target = hass.config_entries.async_get_entry(target_id)
        target_runtime = receivers.get(target_id)
        if target is None or target_runtime is None:
            raise HomeAssistantError("Unknown receiver entry")
        command = call.data["command"].strip()
        try:
            async with target_runtime["lock"]:
                response = await send_command(
                    target.data[CONF_HOST], target.data.get(CONF_PORT, 60128),
                    command, expect_response=command.upper().endswith("QSTN"))
            if not command.upper().endswith("QSTN"):
                await async_query_after_action(hass, target, command)
        except (OSError, ValueError, TimeoutError) as err:
            raise HomeAssistantError(f"Could not send eISCP command: {err}") from err
        hass.bus.async_fire(f"{DOMAIN}_command_sent", {
            "command": command, "response": response, "entry_id": target_id})

    async def async_set_visibility(call):
        from .choices import set_visibility
        target = hass.config_entries.async_get_entry(call.data["entry_id"])
        if target is None or target.domain != DOMAIN or target.entry_id not in hass.data.get(DOMAIN, {}):
            raise HomeAssistantError("Unknown receiver entry")
        try:
            await set_visibility(hass, target, call.data["category"], call.data["choices"])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    import voluptuous as vol
    hass.services.async_register(DOMAIN, "set_visibility", async_set_visibility,
        schema=vol.Schema({vol.Required("entry_id"): str,
            vol.Required("category"): vol.In(("services", "inputs", "modes")),
            vol.Required("choices"): [str]}))
    hass.services.async_register(DOMAIN, "send_command", async_send_command)
    return True


# Stop background work before removing entities so late replies cannot
# update entities that Home Assistant has already unloaded.
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # If platform unload fails, keep the live runtime intact so its entities
    # remain usable. On success no entity will need another callback.
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime:
        runtime["client"].on_message = None
        runtime["client"].on_connection = None
        for key in ("periodic_task", "refresh_task", "bootstrap_task"):
            task = runtime.get(key)
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(runtime.get(key) for key in
            ("periodic_task", "refresh_task", "bootstrap_task") if runtime.get(key)),
            return_exceptions=True)
        await runtime["client"].close()
        CLIENTS.pop((entry.data[CONF_HOST], entry.data.get(CONF_PORT, 60128)), None)
        hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data.get(DOMAIN) and hass.services.has_service(DOMAIN, "send_command"):
        hass.services.async_remove(DOMAIN, "send_command")
        hass.services.async_remove(DOMAIN, "set_visibility")
    return True


async def _bootstrap_receiver(hass, entry, runtime):
    """Read initial player states in the background using the paced connection.

    No initial action changes power, source or volume. Secondary-zone features
    are queried only for zones the receiver reported as supported.
    """
    from .receiver_data import ZONE_COMMANDS
    from .sync import async_query
    missed = []
    for zone in runtime["zones"]:
        for field, prefix in ZONE_COMMANDS[zone].items():
            # A fixed-output secondary zone has no adjustable amplifier volume.
            if zone != "1" and not runtime["capabilities"]["zones"][zone]["volmax"] and field in ("volume", "mute", "mode"):
                continue
            if prefix is not None:
                response = await async_query(hass, entry, prefix + "QSTN")
                if zone == "1" and not response and field != "preset":
                    missed.append(prefix + "QSTN")
    for command in ("NMSQSTN", "HDOQSTN", "IFAQSTN", "IFVQSTN", "CTLQSTN", "SWLQSTN"):
        await async_query(hass, entry, command)
    # Queries are safe to retry once; actions must never be repeated here.
    # A receiver may still be waking up when the first startup query arrives.
    if missed:
        await asyncio.sleep(2)
        for command in missed:
            await async_query(hass, entry, command)


# Apply simple options in memory without reloading the whole integration.
# Changes that affect entity construction still request a normal reload.
async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is None:
        return
    old, new = runtime["options_snapshot"], dict(entry.options)
    runtime["options_snapshot"] = new
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    if changed <= {"shown_inputs", "shown_modes", CONF_VISIBLE_SERVICES, CONF_SHOW_HIDDEN,
                   CONF_UPDATE_AFTER_INPUT, CONF_UPDATE_PERIOD_MINUTES, CONF_EXTENDED_REFRESH}:
        updates = {
            "include_extended": bool(get_setting(entry, CONF_EXTENDED_REFRESH, False)),
            "visible_services": initial_visible_services(entry),
            "update_after_input": bool(get_setting(entry, CONF_UPDATE_AFTER_INPUT, True)),
            "period_minutes": max(0.0, min(60.0, round(float(get_setting(entry, CONF_UPDATE_PERIOD_MINUTES, DEFAULT_UPDATE_PERIOD_MINUTES)), 1))),
        }
        runtime_changed = {key for key, value in updates.items() if runtime[key] != value}
        runtime.update(updates)
        if "period_minutes" in runtime_changed:
            runtime["timer_changed"].set()
        # Local controls already update runtime and publish immediately. Only
        # options edited elsewhere need an additional notification here.
        entities = list(runtime["select_entities"]) if changed & {"shown_inputs", "shown_modes"} else []
        if "visible_services" in runtime_changed:
            entities.extend(runtime["select_entities"])
            entities.extend(entity for entity in runtime["visibility_entities"]
                            if entity.option_key == CONF_VISIBLE_SERVICES)
        if "update_after_input" in runtime_changed:
            entities.extend(entity for entity in runtime["visibility_entities"]
                            if entity.option_key == CONF_UPDATE_AFTER_INPUT)
        if "include_extended" in runtime_changed:
            entities.extend(entity for entity in runtime["visibility_entities"]
                            if entity.option_key == CONF_EXTENDED_REFRESH)
        if "period_minutes" in runtime_changed:
            entities.extend(runtime["number_entities"])
        for entity in entities:
            entity.async_write_ha_state()
        return
    await hass.config_entries.async_reload(entry.entry_id)
