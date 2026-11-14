"""Receiver state readback sensors and user-defined query sensors."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, INPUT_BY_ID
from .eiscp import send_command


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [CurrentNetworkServiceSensor(hass, entry), CurrentInputSensor(hass, entry),
         CurrentMuteStateSensor(hass, entry), CurrentVolumeSensor(hass, entry)]
        + [InformationSensor(hass, entry, *item) for item in INFORMATION_SENSORS]
        + [DiagnosticSensor(hass, entry, *item) for item in DIAGNOSTIC_SENSORS]
        + [CustomCommandSensor(entry, item)
           for item in hass.data[DOMAIN][entry.entry_id]["commands"] if item["type"] == "sensor"]
    )


# Built-in sensors read a shared cache. They do not each poll the receiver,
# which would multiply network traffic. sync_keys limits state notifications.
class ReceiverSyncSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
            manufacturer="Onkyo", model="HT-R997",
        )
        hass.data[DOMAIN][entry.entry_id]["sync_entities"].append(self)

    @property
    def runtime(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]

    @property
    def available(self):
        return self.runtime["connected"]


# Keep the last decoded service, but label it inactive when the receiver is
# on another input. Expose the raw reply for troubleshooting.
class CurrentNetworkServiceSensor(ReceiverSyncSensor):
    sync_keys = frozenset(('input_available', 'input_code', 'current_service', 'service_id', 'nms_response'))
    _attr_name = "Current Network Service"
    _attr_icon = "mdi:music-box-multiple"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_network_service".lower()

    @property
    def native_value(self):
        runtime = self.runtime
        if runtime["input_available"] and runtime["input_code"] != "2B":
            return "Not on NET"
        return runtime["current_service"] or ("Unknown service" if runtime["service_id"] else None)

    @property
    def extra_state_attributes(self):
        return {"service_id": self.runtime["service_id"],
                "raw_nms_response": self.runtime["nms_response"]}


class CurrentInputSensor(ReceiverSyncSensor):
    sync_keys = frozenset(('input_code',))
    _attr_name = "Current Input"
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_input".lower()

    @property
    def native_value(self):
        code = self.runtime["input_code"]
        return None if code is None else INPUT_BY_ID.get(code.upper(), f"Input {code}")

    @property
    def extra_state_attributes(self):
        return {"input_code": self.runtime["input_code"]}


class CurrentMuteStateSensor(ReceiverSyncSensor):
    sync_keys = frozenset(('mute_state',))
    _attr_name = "Current Mute State"
    _attr_icon = "mdi:volume-off"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_mute_state".lower()

    @property
    def native_value(self):
        return self.runtime["mute_state"]


# Legacy compatibility: this sensor retains the requested percent label.
# Its value is the raw hex-to-decimal reading, not a calibrated percentage.
class CurrentVolumeSensor(ReceiverSyncSensor):
    sync_keys = frozenset(('volume',))
    _attr_name = "Current Volume"
    _attr_icon = "mdi:volume-high"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_volume".lower()

    @property
    def native_value(self):
        return self.runtime["volume"]


# Custom query sensors retain their existing independent polling behaviour.
class CustomCommandSensor(SensorEntity):
    def __init__(self, entry, config):
        self.entry, self.config = entry, config
        self._attr_name = config["name"]
        self._attr_unique_id = f"custom_sensor_{config['name'].lower().replace(' ', '_')}".lower()
        self._attr_icon = config.get("icon", "mdi:eye")
        self._attr_native_value = None

    async def async_update(self):
        command = self.config.get("state_command", self.config["command"])
        response = await send_command(self.entry.data["host"], self.entry.data.get("port", 60128), command)
        self._attr_native_value = response or "No response"


# Each row creates a readable sensor without repeating the same class eight
# times. Values are kept as text because a receiver may report "Unknown" or
# combine a resolution and frame rate in one field.
INFORMATION_SENSORS = (
    ("Audio Input", "audio_info", "input_port", "mdi:audio-input-rca"),
    ("Audio Format", "audio_info", "format", "mdi:surround-sound"),
    ("Audio Sample Rate", "audio_info", "sample_rate", "mdi:waveform"),
    ("Audio Input Channels", "audio_info", "input_channels", "mdi:speaker-multiple"),
    ("Current Listening Mode", "audio_info", "listening_mode", "mdi:surround-sound"),
    ("Audio Output Channels", "audio_info", "output_channels", "mdi:speaker-multiple"),
    ("Video Input Resolution", "video_info", "input_resolution", "mdi:video-input-hdmi"),
    ("Video Output Resolution", "video_info", "output_resolution", "mdi:monitor"),
)


class InformationSensor(ReceiverSyncSensor):
    """Display a field; expose the whole decoded reply in the entity attributes."""

    def __init__(self, hass, entry, name, group, field, icon):
        super().__init__(hass, entry)
        self.info_group, self.field = group, field
        self._attr_name, self._attr_icon = name, icon
        self._attr_unique_id = f"{entry.entry_id}_{group}_{field}".lower()
        self.sync_keys = frozenset({group})
        if field == "listening_mode":
            self.sync_keys |= {"zone_1"}

    @property
    def native_value(self):
        if self.field == "listening_mode":
            from .receiver_data import LISTENING_MODES
            code = self.runtime["zones"]["1"]["mode"]
            if code is not None:
                modes = self.entry.options.get("listening_modes") or LISTENING_MODES
                return modes.get(code, code)
        return self.runtime[self.info_group].get(self.field)

    @property
    def extra_state_attributes(self):
        return self.runtime[self.info_group]


# Diagnostics describe query results and their age. Push messages update
# controls separately, so a quiet connection can still have an old query time.
DIAGNOSTIC_SENSORS = (
    ("Last Query Result", "query_status", None),
    ("Last Successful Response", "last_success", SensorDeviceClass.TIMESTAMP),
    ("Last Refresh Completed", "last_refresh", SensorDeviceClass.TIMESTAMP),
    ("Consecutive Query Failures", "query_failures", None),
)


class DiagnosticSensor(ReceiverSyncSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self):
        # Diagnostics must remain readable precisely when the receiver is offline.
        return True

    def __init__(self, hass, entry, name, key, device_class):
        super().__init__(hass, entry)
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_diagnostic_{key}".lower()
        self._attr_device_class = device_class
        self._attr_icon = "mdi:connection"
        self.sync_keys = frozenset({key})
        if key == "query_status":
            self.sync_keys |= {"last_query", "last_response", "query_error"}

    @property
    def native_value(self):
        return self.runtime[self.key]

    @property
    def extra_state_attributes(self):
        if self.key == "query_status":
            return {"command": self.runtime["last_query"],
                    "response": self.runtime["last_response"],
                    "error": self.runtime["query_error"]}
        return {}

