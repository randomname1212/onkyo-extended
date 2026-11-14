"""Receiver capabilities and zone commands, kept separate from the UI code."""
from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .const import INPUT_BY_ID

# Reading this small, packaged table once during module import is sufficient.
# It comes from the published Onkyo eISCP listening-mode definitions.
LISTENING_MODES = json.loads(Path(__file__).with_name("listening_modes.json").read_text())
ZONE_COMMANDS = {
    "1": dict(power="PWR", volume="MVL", mute="AMT", source="SLI", mode="LMD", preset="PRS"),
    "2": dict(power="ZPW", volume="ZVL", mute="ZMT", source="SLZ", mode="LMZ", preset="PRZ"),
    "3": dict(power="PW3", volume="VL3", mute="MT3", source="SL3", mode=None, preset="PR3"),
    "4": dict(power="PW4", volume="VL4", mute="MT4", source="SL4", mode=None, preset="PR4"),
}
CHANNELS = ("Front Left", "Front Right", "Centre", "Surround Left", "Surround Right",
            "Surround Back Left", "Surround Back Right", "Subwoofer 1", "Height 1 Left",
            "Height 1 Right", "Height 2 Left", "Height 2 Right", "Subwoofer 2")
HDMI_OUTPUTS = {"00": "Analog", "01": "Main", "02": "Sub", "03": "Both",
                "04": "Both (Main priority)", "05": "Both (Sub priority)"}


def decode_capabilities(response):
    """Discover only supported zones/inputs; retain conservative main defaults."""
    data = dict(model="Onkyo receiver", identifier=None,
                zones={"1": {"name": "Main", "volmax": 82, "volstep": 1}},
                inputs={code: {"name": name, "zone": 1} for code,name in INPUT_BY_ID.items()})
    if not response or "<" not in response:
        return data
    try:
        tree = ET.fromstring(response[response.index("<"):])
        device = tree.find("device")
        if device is None:
            return data
        data["model"] = device.findtext("model") or data["model"]
        data["identifier"] = device.findtext("deviceserial")
        for element in device.findall("./zonelist/zone"):
            zone = element.get("id")
            if zone in ZONE_COMMANDS and element.get("value") == "1":
                data["zones"][zone] = {
                    "name": element.get("name", f"Zone {zone}"),
                    "volmax": int(element.get("volmax", "0")),
                    "volstep": int(element.get("volstep", "1")),
                }
        inputs = {}
        for element in device.findall("./selectorlist/selector"):
            code = element.get("id", "").upper()
            if element.get("value") == "1" and len(code) == 2:
                inputs[code] = {"name": element.get("name", code),
                                "zone": int(element.get("zone", "01"), 16)}
        if inputs:
            data["inputs"] = inputs
    except (ET.ParseError, ValueError):
        # A bad metadata response must not invent unsupported secondary zones.
        return data
    return data


def initial_zone_states(capabilities):
    return {zone: dict(power=None, volume=None, mute=None, source=None, mode=None, preset=None)
            for zone in capabilities["zones"]}
