"""Network-service visibility, refresh gate, and user-defined switches."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import (
    DOMAIN, SERVICES, CONF_VISIBLE_SERVICES, CONF_SHOW_HIDDEN,
    CONF_UPDATE_AFTER_INPUT, CONF_EXTENDED_REFRESH,
)
from .eiscp import send_command
from .sync import async_query_after_action
from .receiver_data import CHANNELS
import re


def device_info(entry):
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
                      manufacturer="Onkyo", model="HT-R997")


async def async_setup_entry(hass, entry, async_add_entities):
    # Probe channel muting once. Unsupported receivers must not acquire 13
    # permanently broken switches or be repeatedly polled for this feature.
    try:
        response = await send_command(entry.data["host"], entry.data.get("port",60128), "CMTQSTN")
    except (OSError, ValueError, TimeoutError):
        response = None
    if response and re.fullmatch(r"CMT(?:00|01){13}", response):
        hass.data[DOMAIN][entry.entry_id]["channel_mutes"] = [
            response[i:i+2] == "01" for i in range(3,29,2)]
    async_add_entities(
        [UpdateAfterInputSwitch(hass, entry),
         ExtendedInformationSwitch(hass, entry)]
        + [CustomCommandSwitch(hass, entry, item)
           for item in hass.data[DOMAIN][entry.entry_id]["commands"] if item["type"] == "switch"]
        + ([ChannelMuteSwitch(hass, entry, i, name) for i,name in enumerate(CHANNELS)]
           if hass.data[DOMAIN][entry.entry_id]["channel_mutes"] is not None else [])
    )


class UpdateAfterInputSwitch(SwitchEntity):
    option_key = CONF_UPDATE_AFTER_INPUT
    _attr_has_entity_name = True
    _attr_name = "Update Values After Input"
    _attr_icon = "mdi:sync"
    _attr_should_poll = False

    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_update_values_after_input".lower()
        self._attr_device_info = device_info(entry)
        hass.data[DOMAIN][entry.entry_id]["visibility_entities"].append(self)

    @property
    def is_on(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]["update_after_input"]

    async def _set(self, enabled):
        self.hass.data[DOMAIN][self.entry.entry_id]["update_after_input"] = enabled
        self.async_write_ha_state()
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_UPDATE_AFTER_INPUT: enabled}
        )

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)


# Custom switches are optimistic: their state records the requested action,
# because arbitrary user commands do not have a known state decoder.
class CustomCommandSwitch(SwitchEntity):
    def __init__(self, hass, entry, config):
        self.hass, self.entry, self.config = hass, entry, config
        self._attr_name = config["name"]
        self._attr_unique_id = f"custom_switch_{config['name'].lower().replace(' ', '_')}".lower()
        self._attr_icon = config.get("icon", "mdi:toggle-switch")
        self._attr_is_on = False

    async def async_turn_on(self, **kwargs):
        await send_command(self.entry.data["host"], self.entry.data.get("port", 60128),
                           self.config["command"], expect_response=False)
        self._attr_is_on = True
        self.async_write_ha_state()
        await async_query_after_action(self.hass, self.entry, self.config["command"])

    async def async_turn_off(self, **kwargs):
        command = self.config.get("off_command")
        if not command:
            return
        await send_command(self.entry.data["host"], self.entry.data.get("port", 60128),
                           command, expect_response=False)
        self._attr_is_on = False
        self.async_write_ha_state()
        await async_query_after_action(self.hass, self.entry, command)


class ExtendedInformationSwitch(SwitchEntity):
    """Persist the opt-in setting; the existing refresh worker uses it next run."""
    option_key = CONF_EXTENDED_REFRESH
    _attr_has_entity_name = True
    _attr_name = "Include Extended Information In Refresh"
    _attr_icon = "mdi:information-outline"
    _attr_should_poll = False

    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_extended_information".lower()
        self._attr_device_info = device_info(entry)
        hass.data[DOMAIN][entry.entry_id]["visibility_entities"].append(self)

    @property
    def is_on(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]["include_extended"]

    async def _set(self, enabled):
        if self.is_on == enabled:
            return
        self.hass.data[DOMAIN][self.entry.entry_id]["include_extended"] = enabled
        self.async_write_ha_state()
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_EXTENDED_REFRESH: enabled})

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)


class ChannelMuteSwitch(SwitchEntity):
    """Mute one channel while preserving all the other channels' mute states."""
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:volume-mute"
    sync_keys = frozenset({"channel_mutes", "connected"})

    def __init__(self, hass, entry, index, name):
        self.hass, self.entry, self.index = hass, entry, index
        self._attr_name = f"Mute {name}"
        self._attr_unique_id = f"{entry.entry_id}_channel_mute_{index}".lower()
        self._attr_device_info = device_info(entry)
        hass.data[DOMAIN][entry.entry_id]["sync_entities"].append(self)

    @property
    def is_on(self):
        values = self.hass.data[DOMAIN][self.entry.entry_id]["channel_mutes"]
        return None if values is None else values[self.index]

    @property
    def available(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]["connected"]

    async def _set(self, muted):
        runtime = self.hass.data[DOMAIN][self.entry.entry_id]
        async with runtime["lock"]:
            response = await send_command(self.entry.data["host"], self.entry.data.get("port",60128), "CMTQSTN")
            if not response or not re.fullmatch(r"CMT(?:00|01){13}", response):
                raise ValueError("Receiver did not confirm channel mute states")
            values = [response[i:i+2] for i in range(3,29,2)]
            values[self.index] = "01" if muted else "00"
            await send_command(self.entry.data["host"], self.entry.data.get("port",60128),
                               "CMT" + "".join(values), expect_response=False)

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)
