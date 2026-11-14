from __future__ import annotations
import json
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN, CONF_HOST, CONF_PORT, CONF_DELAY, CONF_VERIFY, CONF_CUSTOM_YAML,
    CONF_SHOW_HIDDEN, CONF_UPDATE_AFTER_INPUT, CONF_UPDATE_PERIOD_MINUTES,
    DEFAULT_UPDATE_PERIOD_MINUTES, DEFAULT_PORT, DEFAULT_DELAY,
)
from .eiscp import send_command
from .sync import async_read_nms, decode_nms_service_id


# Initial setup checks reachability using a read-only query and stores the
# receiver address. No audio setting changes during configuration.
class OnkyoNetworkServicesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_ssdp(self, discovery_info):
        """Offer a discovered receiver; do not create or control it silently."""
        self._discovered_host = urlparse(discovery_info.ssdp_location).hostname
        await self.async_set_unique_id(f"{self._discovered_host}:60128")
        self._abort_if_unique_id_configured()
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input=None):
        """Update an existing receiver's address without changing its entities."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            try:
                response = await async_read_nms(user_input[CONF_HOST], user_input[CONF_PORT])
                if response is None:
                    raise ValueError("No receiver response")
            except (OSError, ValueError, TimeoutError):
                return self.async_show_form(step_id="reconfigure",data_schema=vol.Schema({
                    vol.Required(CONF_HOST,default=entry.data[CONF_HOST]):str,
                    vol.Required(CONF_PORT,default=entry.data.get(CONF_PORT,60128)):vol.Coerce(int)}),errors={"base":"cannot_connect"})
            return self.async_update_reload_and_abort(entry,data_updates=user_input)
        return self.async_show_form(step_id="reconfigure",data_schema=vol.Schema({
            vol.Required(CONF_HOST,default=entry.data[CONF_HOST]):str,
            vol.Required(CONF_PORT,default=entry.data.get(CONF_PORT,60128)):vol.Coerce(int)}))

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            previous = next((entry for entry in self.hass.config_entries.async_entries()
                if entry.domain != DOMAIN and entry.domain.startswith("onkyo_")
                and entry.data.get(CONF_HOST) == host), None)
            if previous and previous.disabled_by is None:
                return self.async_abort(reason="other_integration_active")
            try:
                # A harmless query confirms TCP reachability; no receiver state is changed.
                response = await async_read_nms(host, user_input[CONF_PORT], timeout=2.5)
                if response is None:
                    raise ValueError("No response from receiver")
            except (OSError, ValueError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{host}:{user_input[CONF_PORT]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Onkyo Extended ({host})",
                    data={**(dict(previous.data) if previous else {}), **user_input},
                    options=dict(previous.options) if previous else {},
                )

        schema = vol.Schema({
            vol.Required(CONF_HOST,default=getattr(self,"_discovered_host", "")): str,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OnkyoNetworkServicesOptionsFlow()


# Options pages configure service visibility, timing and custom YAML.
# Extended polling has its own switch entity and is off by default.
class OnkyoNetworkServicesOptionsFlow(config_entries.OptionsFlow):
    def __init__(self):
        self._discovered_command = None
        self._discovery_response = None

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["visibility", "settings", "receiver", "custom_commands", "discovery"],
        )

    async def async_step_visibility(self, user_input=None):
        """Three checkbox lists replace a switch entity for every option."""
        from .choices import catalog, shown_keys, CATEGORIES
        runtime = self.hass.data[DOMAIN][self.config_entry.entry_id]
        if user_input is not None:
            from .const import CONF_VISIBLE_SERVICES
            services = catalog(runtime, self.config_entry, "services")
            updates = {CONF_VISIBLE_SERVICES: {key: key in user_input["services"] for key in services},
                       "shown_inputs": user_input["inputs"], "shown_modes": user_input["modes"]}
            return self.async_create_entry(title="", data={**self.config_entry.options, **updates})
        fields = {}
        for category in CATEGORIES:
            values = catalog(runtime, self.config_entry, category)
            fields[vol.Required(category, default=shown_keys(runtime, self.config_entry, category))] = selector.SelectSelector(
                selector.SelectSelectorConfig(multiple=True, mode=selector.SelectSelectorMode.DROPDOWN,
                    options=[{"value": key, "label": label} for key, label in values.items()]))
        return self.async_show_form(step_id="visibility", data_schema=vol.Schema(fields))

    async def async_step_receiver(self, user_input=None):
        """Name inputs/modes and scale HA volume; never change hardware here."""
        errors={}
        if user_input is not None:
            try:
                result=dict(user_input)
                for key in ("input_names","listening_modes"):
                    parsed=json.loads(result[key] or "{}")
                    if not isinstance(parsed,dict) or any(
                        not isinstance(k,str) or len(k)!=2 or
                        any(c not in "0123456789ABCDEFabcdef" for c in k) or
                        not isinstance(v,str) or not v.strip() for k,v in parsed.items()):
                        raise ValueError("Use hexadecimal codes mapped to names")
                    if len(set(parsed.values())) != len(parsed):
                        raise ValueError("Names must be unique")
                    result[key]={k.upper():v for k,v in parsed.items()}
                return self.async_create_entry(title="",data={**self.config_entry.options,**result})
            except (ValueError,TypeError):
                errors["base"]="invalid_mapping"
        current=self.config_entry.options
        return self.async_show_form(step_id="receiver",errors=errors,data_schema=vol.Schema({
            vol.Optional("volume_resolution",default=current.get("volume_resolution",82)):
                selector.NumberSelector(selector.NumberSelectorConfig(min=1,max=200,step=1,mode=selector.NumberSelectorMode.BOX)),
            vol.Optional("max_volume",default=current.get("max_volume",100)):
                selector.NumberSelector(selector.NumberSelectorConfig(min=1,max=100,step=1,mode=selector.NumberSelectorMode.BOX)),
            vol.Optional("input_names",default=json.dumps(current.get("input_names",{}),indent=2)):
                selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Optional("listening_modes",default=json.dumps(current.get("listening_modes",{}),indent=2)):
                selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        }))

    async def async_step_settings(self, user_input=None):
        if user_input is not None:
            options = {**self.config_entry.options, **user_input}
            # Apply this master setting consistently to individual services.
            if user_input.get(CONF_SHOW_HIDDEN) != self.config_entry.options.get(CONF_SHOW_HIDDEN, False):
                from .const import SERVICES, CONF_VISIBLE_SERVICES
                options[CONF_VISIBLE_SERVICES] = dict.fromkeys(SERVICES, bool(user_input[CONF_SHOW_HIDDEN]))
            return self.async_create_entry(title="", data=options)
        current = self.config_entry.options
        schema = vol.Schema({
            vol.Optional(CONF_DELAY, default=current.get(CONF_DELAY, DEFAULT_DELAY)):
                selector.NumberSelector(selector.NumberSelectorConfig(
                    min=0, max=15, step=0.25, mode=selector.NumberSelectorMode.BOX
                )),
            vol.Optional(CONF_VERIFY, default=current.get(CONF_VERIFY, False)): bool,
            vol.Optional(CONF_SHOW_HIDDEN, default=current.get(CONF_SHOW_HIDDEN, False)): bool,
            vol.Optional(CONF_UPDATE_AFTER_INPUT, default=current.get(CONF_UPDATE_AFTER_INPUT, True)): bool,
            vol.Optional(CONF_UPDATE_PERIOD_MINUTES, default=current.get(CONF_UPDATE_PERIOD_MINUTES, DEFAULT_UPDATE_PERIOD_MINUTES)):
                selector.NumberSelector(selector.NumberSelectorConfig(
                    min=0, max=60, step=0.1, unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX
                )),
        })
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_custom_commands(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data={**self.config_entry.options, **user_input})
        current = self.config_entry.options
        yaml_default = current.get(CONF_CUSTOM_YAML, DEFAULT_CUSTOM_YAML)
        schema = vol.Schema({
            vol.Optional(CONF_CUSTOM_YAML, default=yaml_default):
                selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        })
        return self.async_show_form(step_id="custom_commands", data_schema=schema)

    async def async_step_discovery(self, user_input=None):
        host = self.config_entry.data[CONF_HOST]
        port = self.config_entry.data.get(CONF_PORT, DEFAULT_PORT)
        response = await async_read_nms(host, port, timeout=3)
        code = decode_nms_service_id(response)
        payload = str(response or "No response")
        self._discovery_response = payload
        self._discovered_command = f"NSV{code}0" if code else None
        return self.async_show_form(
            step_id="discovery",
            data_schema=vol.Schema({}),
            description_placeholders={
                "query": "NMSQSTN",
                "response": str(response or "No response"),
                "derived": self._discovered_command or "Could not derive a service command",
                "status": "Valid service identifier found." if code else payload,
            },
        )

    async def async_step_discovery_test(self, user_input=None):
        if user_input is not None:
            host = self.config_entry.data[CONF_HOST]
            port = self.config_entry.data.get(CONF_PORT, DEFAULT_PORT)
            try:
                result = await send_command(host, port, self._discovered_command, timeout=3, expect_response=False)
                return self.async_show_form(
                    step_id="discovery_test",
                    data_schema=vol.Schema({}),
                    description_placeholders={
                        "command": self._discovered_command,
                        "result": str(result or "Command sent; receiver returned no immediate response."),
                    },
                )
            except (OSError, ValueError) as err:
                return self.async_abort(reason="test_failed")
        return self.async_show_form(
            step_id="discovery_test",
            data_schema=vol.Schema({}),
            description_placeholders={"command": self._discovered_command or "Unavailable"},
        )


DEFAULT_CUSTOM_YAML = """# Custom eISCP entities. Entity IDs are generated from the name.
# Supported types: button, switch, select, sensor.
# For a switch, add off_command. For a select, add options as label: command.
# For a sensor, add state_command (query) to retrieve a state response.
#
# - name: Spotify
#   type: button
#   command: NSV0A0
#   icon: mdi:spotify
#
# - name: Custom Power
#   type: switch
#   command: PWR01
#   off_command: PWR00
#   icon: mdi:power
#
# - name: My Service
#   type: select
#   command: NSV0A0
#   options:
#     Spotify: NSV0A0
#     TuneIn: NSV0E0
#
# - name: Receiver Query
#   type: sensor
#   command: NMSQSTN
#   state_command: NMSQSTN
#   icon: mdi:information
"""
