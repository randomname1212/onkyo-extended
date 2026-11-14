"""Network services and custom select entities."""
from __future__ import annotations

import asyncio
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, SERVICES, CONF_DELAY, DEFAULT_DELAY
from . import get_setting
from .eiscp import send_command
from .sync import async_query_after_action
from .choices import catalog, attributes


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [NetworkServiceSelect(hass, entry), ReceiverChoiceSelect(hass, entry, "inputs"),
         ReceiverChoiceSelect(hass, entry, "modes")]
        + [CustomCommandSelect(hass, entry, item)
           for item in hass.data[DOMAIN][entry.entry_id]["commands"]
           if item["type"] == "select"]
    )


# Select a network service in two steps: switch to NET, wait the configured
# delay, then launch the service. Readback remains controlled by its switch.
class NetworkServiceSelect(SelectEntity):
    sync_keys = frozenset({"current_service"})
    _attr_has_entity_name = True
    _attr_name = "Network Services"
    _attr_icon = "mdi:format-list-numbered"
    _attr_should_poll = False

    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_network_services".lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
            manufacturer="Onkyo", model="HT-R997",
        )
        hass.data[DOMAIN][entry.entry_id]["sync_entities"].append(self)
        hass.data[DOMAIN][entry.entry_id]["select_entities"].append(self)

    @property
    def available(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]["connected"]

    @property
    def options(self):
        return list(SERVICES)

    @property
    def extra_state_attributes(self):
        return attributes(self.hass.data[DOMAIN][self.entry.entry_id], self.entry, "services")

    @property
    def current_option(self):
        runtime = self.hass.data[DOMAIN][self.entry.entry_id]
        selected = runtime["current_service"]
        # Hidden active services remain visible in the separate status sensor.
        return selected if selected in self.options else None

    async def async_select_option(self, option):
        if option not in self.options:
            raise ValueError(f"Unknown network service: {option}")
        host, port = self.entry.data["host"], self.entry.data.get("port", 60128)
        delay = float(get_setting(self.entry, CONF_DELAY, DEFAULT_DELAY))
        runtime = self.hass.data[DOMAIN][self.entry.entry_id]
        async with runtime["lock"]:
            # SLI/NSV are actions: ACK not required (the receiver may send none).
            await send_command(host, port, "SLI2B", expect_response=False)
            await asyncio.sleep(delay)
            await send_command(host, port, SERVICES[option], expect_response=False)
        await asyncio.sleep(0.75)
        await async_query_after_action(self.hass, self.entry, SERVICES[option])


class ReceiverChoiceSelect(SelectEntity):
    """Expose real receiver state; selecting an item never updates optimistically."""
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass, entry, category):
        self.hass, self.entry, self.category = hass, entry, category
        self._attr_name = "Input Selection" if category == "inputs" else "Listening Modes"
        self._attr_icon = "mdi:video-input-hdmi" if category == "inputs" else "mdi:surround-sound"
        self._attr_unique_id = f"{entry.entry_id}_{'input_selection' if category == 'inputs' else 'listening_modes'}".lower()
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title, manufacturer="Onkyo", model=self.runtime["capabilities"]["model"])
        self.sync_keys = frozenset({"zone_1", "connected"})
        self.runtime["sync_entities"].append(self)
        self.runtime["select_entities"].append(self)

    @property
    def runtime(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]

    @property
    def available(self):
        return self.runtime["connected"]

    @property
    def options(self):
        return list(catalog(self.runtime, self.entry, self.category).values())

    @property
    def current_option(self):
        field = "source" if self.category == "inputs" else "mode"
        code = self.runtime["zones"]["1"][field]
        return catalog(self.runtime, self.entry, self.category).get(code)

    @property
    def extra_state_attributes(self):
        return attributes(self.runtime, self.entry, self.category)

    async def async_select_option(self, option):
        from .sync import async_query
        available = catalog(self.runtime, self.entry, self.category)
        code = next((code for code, label in available.items() if label == option), None)
        if code is None:
            raise ValueError("Unknown receiver choice")
        prefix = "SLI" if self.category == "inputs" else "LMD"
        await send_command(self.entry.data["host"], self.entry.data.get("port", 60128),
                           prefix + code, expect_response=False)
        if self.runtime["update_after_input"]:
            await asyncio.sleep(0.5)
            await async_query(self.hass, self.entry, prefix + "QSTN")


# A custom select maps owner-provided option labels to raw commands.
class CustomCommandSelect(SelectEntity):
    def __init__(self, hass, entry, config):
        self.hass, self.entry, self.config = hass, entry, config
        self._attr_name = config["name"]
        self._attr_unique_id = f"custom_select_{config['name'].lower().replace(' ', '_')}".lower()
        self._attr_icon = config.get("icon", "mdi:format-list-bulleted")
        self._attr_options = list(config.get("options", {}))
        self._attr_current_option = self._attr_options[0] if self._attr_options else None

    @property
    def options(self):
        return self._attr_options

    async def async_select_option(self, option):
        command = self.config["options"][option]
        await send_command(self.entry.data["host"], self.entry.data.get("port", 60128),
                           command, expect_response=False)
        self._attr_current_option = option
        self.async_write_ha_state()
