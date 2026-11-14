"""User-adjustable periodic polling timer in minutes (zero disables)."""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity import DeviceInfo
from .eiscp import send_command
from .sync import async_query_after_action
from .extended import LEVEL_CONTROLS, encode_level
from .const import (
    DOMAIN, CONF_UPDATE_PERIOD_MINUTES,
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PeriodicTimerNumber(hass, entry)]
                       + [SpeakerLevelNumber(hass, entry, prefix) for prefix in LEVEL_CONTROLS])


# This box controls scheduling only; it does not change receiver settings.
# Fractional minutes are preserved in saved options, including after restart.
class PeriodicTimerNumber(NumberEntity):
    _attr_has_entity_name = True
    _attr_name = "Update Values Periodic Timer"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "min"
    _attr_should_poll = False

    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_periodic_timer".lower()
        hass.data[DOMAIN][entry.entry_id]["number_entities"].append(self)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
            manufacturer="Onkyo", model="HT-R997",
        )

    @property
    def native_value(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]["period_minutes"]

    async def async_set_native_value(self, value: float):
        minutes = round(float(value), 1)
        if not 0 <= minutes <= 60:
            raise ValueError("Periodic timer must be between 0 and 60 minutes")
        runtime = self.hass.data[DOMAIN][self.entry.entry_id]
        if runtime["period_minutes"] == minutes:
            return
        runtime["period_minutes"] = minutes
        runtime["timer_changed"].set()
        self.async_write_ha_state()
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_UPDATE_PERIOD_MINUTES: minutes}
        )


class SpeakerLevelNumber(NumberEntity):
    """Set a temporary channel adjustment, not the speaker calibration menu.

    These controls use the HT-R997's verified whole-dB scale. The displayed
    value is the last receiver-confirmed setting. Push acknowledgements update
    it even when extra post-action queries are disabled; manual refresh remains
    available if a receiver does not send an acknowledgement.
    """
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "dB"
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False
    _attr_icon = "mdi:speaker"

    def __init__(self, hass, entry, prefix):
        self.hass, self.entry, self.prefix = hass, entry, prefix
        name, self.key, minimum, maximum = LEVEL_CONTROLS[prefix]
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{self.key}".lower()
        self._attr_native_min_value, self._attr_native_max_value = minimum, maximum
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
            manufacturer="Onkyo", model="HT-R997",
        )
        self.sync_keys = frozenset({self.key})
        hass.data[DOMAIN][entry.entry_id]["sync_entities"].append(self)

    @property
    def native_value(self):
        return self.hass.data[DOMAIN][self.entry.entry_id][self.key]

    async def async_set_native_value(self, value):
        # Validation happens before connecting. There is no optimistic update:
        # only a decoded reply is allowed to change the confirmed display.
        command = encode_level(self.prefix, value)
        runtime = self.hass.data[DOMAIN][self.entry.entry_id]
        async with runtime["lock"]:
            await send_command(self.entry.data["host"], self.entry.data.get("port", 60128),
                               command, expect_response=False)
        await async_query_after_action(self.hass, self.entry, command)
