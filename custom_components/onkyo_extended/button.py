"""Remote action buttons and user-defined command buttons."""
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN
from .eiscp import send_command
from .sync import async_query_after_action, schedule_refresh

# Each row defines a button label, raw receiver command and dashboard icon.
# Friendly names can change without changing the command-based entity ID.
REMOTE_COMMANDS = (
    ("Quick Menu", "OSDQUICK", "mdi:tune"),
    ("Movie/TV", "LMDMOVIE", "mdi:movie-open"),
    ("Music", "LMDMUSIC", "mdi:music"),
    ("Game", "LMDGAME", "mdi:controller"),
    ("Shuffle", "NTCRANDOM", "mdi:shuffle"),
    ("OSD Up", "OSDUP", "mdi:arrow-up-bold"),
    ("OSD Down", "OSDDOWN", "mdi:arrow-down-bold"),
    ("OSD Left", "OSDLEFT", "mdi:arrow-left-bold"),
    ("OSD Right", "OSDRIGHT", "mdi:arrow-right-bold"),
    ("OSD Enter", "OSDENTER", "mdi:check-circle"),
    ("OSD Back", "OSDEXIT", "mdi:arrow-u-down-left-bold"),
    ("Settings", "OSDMENU", "mdi:cog"),
    ("Volume Up", "MVLUP", "mdi:volume-plus"),
    ("Volume Down", "MVLDOWN", "mdi:volume-minus"),
    ("Mute Toggle", "AMTTG", "mdi:volume-off"),
    ("Mute Off", "AMT00", "mdi:volume-high"),
    ("Mute On", "AMT01", "mdi:volume-mute"),
    ("Network Settings", "NTCSETUP", "mdi:cog-outline"),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [ReceiverCommandButton(hass, entry, name, command, icon) for name, command, icon in REMOTE_COMMANDS]
        + [ManualRefreshButton(hass, entry), ExtendedRefreshButton(hass, entry)]
        + [CustomCommandButton(hass, entry, item)
           for item in hass.data[DOMAIN][entry.entry_id]["commands"] if item["type"] == "button"]
    )


# Navigation, volume and mute buttons share one send-and-readback path.
class ReceiverCommandButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, hass, entry, name, command, icon):
        self.hass, self.entry, self.command = hass, entry, command
        self._attr_name = name
        # Preserve the existing OSD entity IDs; rename only the friendly names.
        self._attr_unique_id = f"{entry.entry_id}_remote_{command.lower()}".lower()
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
            manufacturer="Onkyo", model="HT-R997",
        )

    async def async_press(self):
        runtime = self.hass.data[DOMAIN][self.entry.entry_id]
        async with runtime["lock"]:
            await send_command(self.entry.data["host"], self.entry.data.get("port", 60128),
                               self.command, expect_response=False)
        await async_query_after_action(self.hass, self.entry, self.command)


# Start a background refresh so the button service does not block for the
# ten-second gaps between queries. Repeated requests are coalesced.
class ManualRefreshButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Manual Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_manual_refresh".lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
            manufacturer="Onkyo", model="HT-R997",
        )

    async def async_press(self):
        schedule_refresh(self.hass, self.entry)


# These buttons come from the owner's YAML rather than the built-in list.
class CustomCommandButton(ButtonEntity):
    def __init__(self, hass, entry, config):
        self.hass, self.entry, self.config = hass, entry, config
        self._attr_name = config["name"]
        self._attr_unique_id = f"custom_button_{config['name'].lower().replace(' ', '_')}".lower()
        self._attr_icon = config.get("icon", "mdi:gesture-tap-button")

    async def async_press(self):
        runtime = self.hass.data[DOMAIN][self.entry.entry_id]
        async with runtime["lock"]:
            await send_command(self.entry.data["host"], self.entry.data.get("port", 60128),
                               self.config["command"], expect_response=False)
        await async_query_after_action(self.hass, self.entry, self.config["command"])


class ExtendedRefreshButton(ManualRefreshButton):
    """Read audio, video and speaker levels without enabling extra polling."""
    _attr_name = "Refresh Extended Information"
    _attr_icon = "mdi:information-refresh-outline"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_extended_refresh".lower()

    async def async_press(self):
        schedule_refresh(self.hass, self.entry, extended_only=True)

