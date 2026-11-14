"""Standard Home Assistant receiver controls using the shared connection.

One media_player entity represents each supported zone. The existing separate
buttons and sensors remain available and keep their old unique IDs.
"""
from __future__ import annotations

import math
import asyncio
import voluptuous as vol
from homeassistant.components.media_player import (
    MediaPlayerEntity, MediaPlayerEntityFeature, MediaPlayerDeviceClass,
    MediaPlayerState,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_platform
from .const import DOMAIN
from .eiscp import send_command
from .receiver_data import ZONE_COMMANDS, LISTENING_MODES, HDMI_OUTPUTS
from .choices import catalog
from .const import INPUT_BY_ID


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReceiverMediaPlayer(hass, entry, zone)
                        for zone in runtime["zones"]])
    # Give HDMI output switching an explicit action rather than pretending it
    # is a physical input source. This service also works in HA automations.
    platform = entity_platform.async_get_current_platform()
    if not hass.services.has_service("media_player", "onkyo_extended_select_hdmi_output"):
        platform.async_register_entity_service(
            "onkyo_extended_select_hdmi_output",
            {vol.Required("output"): vol.In(list(HDMI_OUTPUTS.values()))},
            "async_select_hdmi_output")


class ReceiverMediaPlayer(MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_should_poll = False

    def __init__(self, hass, entry, zone):
        self.hass, self.entry, self.zone = hass, entry, zone
        self.codes = ZONE_COMMANDS[zone]
        runtime = hass.data[DOMAIN][entry.entry_id]
        capabilities = runtime["capabilities"]
        self.zone_info = capabilities["zones"][zone]
        self._attr_name = "Main Zone" if zone == "1" else f"Zone {zone}"
        self._attr_unique_id = f"{entry.entry_id}_receiver_zone_{zone}".lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
            manufacturer="Onkyo", model=capabilities["model"])
        bit = 1 << (int(zone)-1)
        configured = entry.options.get("input_names", {})
        self.inputs = {code: configured.get(code, INPUT_BY_ID.get(code, item["name"]))
                       for code,item in capabilities["inputs"].items() if item["zone"] & bit}
        self.modes = catalog(runtime, entry, "modes")
        self.resolution = float(entry.options.get("volume_resolution") or self.zone_info["volmax"] or 82)
        self.maximum = float(entry.options.get("max_volume", 100)) / 100
        self.sync_keys = frozenset({f"zone_{zone}", "connected", "audio_info", "video_info", "hdmi_output"})
        runtime["sync_entities"].append(self)

    @property
    def runtime(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]

    @property
    def zone_state(self):
        return self.runtime["zones"][self.zone]

    @property
    def available(self):
        return self.runtime["connected"]

    @property
    def state(self):
        value = self.zone_state["power"]
        return None if value is None else (MediaPlayerState.ON if value else MediaPlayerState.OFF)

    @property
    def supported_features(self):
        features = (MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF |
                    MediaPlayerEntityFeature.SELECT_SOURCE | MediaPlayerEntityFeature.PLAY_MEDIA)
        if self.zone == "1" or self.zone_info["volmax"] or self.zone_state["volume"] is not None:
            features |= (MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP |
                         MediaPlayerEntityFeature.VOLUME_MUTE)
        if self.codes["mode"]:
            features |= MediaPlayerEntityFeature.SELECT_SOUND_MODE
        return features

    @property
    def volume_level(self):
        raw = self.zone_state["volume"]
        return None if raw is None else min(1.0, raw / (self.resolution * self.maximum))

    @property
    def is_volume_muted(self):
        return self.zone_state["mute"]

    @property
    def source_list(self):
        return list(self.inputs.values())

    @property
    def source(self):
        code = self.zone_state["source"]
        return self.inputs.get(code, code)

    @property
    def sound_mode_list(self):
        return list(dict.fromkeys(self.modes.values())) if self.codes["mode"] else []

    @property
    def sound_mode(self):
        code = self.zone_state["mode"]
        return self.modes.get(code, code)

    @property
    def extra_state_attributes(self):
        result = {"zone": self.zone_info["name"], "preset": self.zone_state["preset"]}
        if self.zone == "1":
            result.update(audio_information=self.runtime["audio_info"],
                          video_information=self.runtime["video_info"],
                          hdmi_output=HDMI_OUTPUTS.get(self.runtime["hdmi_output"]))
        return result

    async def _send(self, field, value):
        prefix = self.codes[field]
        if prefix is None:
            raise ValueError(f"{field} is unavailable for this zone")
        await send_command(self.entry.data["host"], self.entry.data.get("port",60128),
                           prefix + value, expect_response=False)
        # The shared reader handles acknowledgements; delayed queries are only
        # fallback confirmation, never a reason to repeat the action itself.
        if self.runtime["update_after_input"]:
            await asyncio.sleep(0.5)
            await send_command(self.entry.data["host"], self.entry.data.get("port",60128),
                               prefix + "QSTN")

    async def async_turn_on(self):
        await self._send("power", "01")

    async def async_turn_off(self):
        await self._send("power", "00")

    async def async_set_volume_level(self, volume):
        if not math.isfinite(volume) or not 0 <= volume <= 1:
            raise ValueError("Volume must be between 0 and 1")
        raw = round(volume * self.resolution * self.maximum)
        await self._send("volume", f"{raw:02X}")

    async def async_volume_up(self):
        if self.zone_state["volume"] is not None and self.zone_state["volume"] >= round(self.resolution*self.maximum):
            return
        await self._send("volume", "UP")

    async def async_volume_down(self):
        await self._send("volume", "DOWN")

    async def async_mute_volume(self, mute):
        await self._send("mute", "01" if mute else "00")

    async def async_select_source(self, source):
        code = next((code for code,label in self.inputs.items() if label == source), None)
        if code is None:
            raise ValueError("Unknown input source")
        await self._send("source", code)

    async def async_select_sound_mode(self, sound_mode):
        code = next((code for code,label in self.modes.items() if label == sound_mode), None)
        if code is None:
            raise ValueError("Unknown listening mode")
        await self._send("mode", code)

    async def async_play_media(self, media_type, media_id, **kwargs):
        # Same meaning as the standard integration: radio tuner presets, not
        # arbitrary URLs or Spotify tracks. A tuner input must be active first.
        if str(media_type).lower() != "radio" or self.zone_state["source"] not in ("24","25","33"):
            raise ValueError("Select a tuner input before playing a radio preset")
        preset = int(media_id)
        if not 1 <= preset <= 40:
            raise ValueError("Preset must be between 1 and 40")
        await self._send("preset", f"{preset:02X}")

    async def async_select_hdmi_output(self, output):
        if self.zone != "1":
            raise ValueError("HDMI output belongs to the main zone")
        code = next((code for code,label in HDMI_OUTPUTS.items() if label == output), None)
        if code is None:
            raise ValueError("Unknown HDMI output")
        await send_command(self.entry.data["host"], self.entry.data.get("port",60128),
                           "HDO"+code, expect_response=False)
