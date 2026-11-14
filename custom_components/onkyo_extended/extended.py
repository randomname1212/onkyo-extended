"""Translate the optional signal-information and speaker-level replies.

This module does no networking. Keeping conversion separate makes it possible
to test unusual replies without sending commands to a real receiver.
"""
from __future__ import annotations

import math
import re

# These names describe the comma-separated positions in Onkyo's protocol.
# Empty positions must be retained: NETWORK audio often omits format/rate.
AUDIO_FIELDS = (
    "input_port", "format", "sample_rate", "input_channels", "listening_mode",
    "output_channels", "output_sample_rate", "pqls", "phase_delay", "phase", "upmix_mode",
)
VIDEO_FIELDS = (
    "input_port", "input_resolution", "input_colour", "input_depth",
    "output_port", "output_resolution", "output_colour", "output_depth", "picture_mode", "input_hdr",
)

# HT-R997 reports whole-dB steps in NRIQSTN. The owner confirmed that
# CTL+04 means +4 dB on the receiver. Other models may use half-dB steps.
LEVEL_CONTROLS = {
    "CTL": ("Centre Level", "centre_level", -12, 12),
    "SWL": ("Subwoofer Level", "subwoofer_level", -15, 12),
}
EXTENDED_QUERIES = ("IFAQSTN", "IFVQSTN", "CTLQSTN", "SWLQSTN")


def decode_information(response, prefix, fields):
    """Return named fields, preserving blanks as None and raw text for diagnosis."""
    value = (response or "").strip("\x00\r\n\x1a ").removeprefix("!1")
    if not value.startswith(prefix) or value[len(prefix):] in ("", "N/A"):
        return None
    parts = value[len(prefix):].split(",")
    result = {name: parts[i].strip() or None if i < len(parts) else None
              for i, name in enumerate(fields)}
    result["raw_response"] = value
    return result


def decode_level(response, prefix):
    """Onkyo uses signed hexadecimal: +04 = +4 dB, -0A = -10 dB, 000 = 0."""
    value = (response or "").strip("\x00\r\n\x1a ").removeprefix("!1")
    match = re.fullmatch(re.escape(prefix) + r"([+-][0-9A-Fa-f]{2}|000)", value)
    if not match:
        return None
    result = int(match.group(1), 16)
    _, _, minimum, maximum = LEVEL_CONTROLS[prefix]
    return result if minimum <= result <= maximum else None


def encode_level(prefix, value):
    """Validate before sending; never silently clamp or round a user's setting."""
    _, _, minimum, maximum = LEVEL_CONTROLS[prefix]
    value = float(value)
    if not math.isfinite(value) or not value.is_integer() or not minimum <= value <= maximum:
        raise ValueError(f"{prefix} level must be a whole number from {minimum} to {maximum} dB")
    number = int(value)
    suffix = "000" if number == 0 else f"{'+' if number > 0 else '-'}{abs(number):02X}"
    return prefix + suffix
