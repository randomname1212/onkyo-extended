"""Minimal asynchronous eISCP transport, independent of the official integration."""
from __future__ import annotations

import asyncio
import re
import struct
from typing import Optional

HEADER = b"ISCP"
PREFIX = b"!1"
SUFFIX = b"\r"

# Active runtime clients are shared even by legacy custom YAML entities. Setup
# registers one client; unloading removes it. Config-flow probes can still use
# a short-lived connection when no receiver entry exists yet.
CLIENTS = {}



# A command is wrapped in the 16-byte ISCP network header before sending.
# Signed arguments are used by centre/subwoofer temporary-level commands.
def encode_packet(command: str) -> bytes:
    command = command.strip()
    if not re.fullmatch(r"[A-Z0-9]{3}[A-Za-z0-9+-]*", command):
        raise ValueError(f"Invalid eISCP command: {command!r}")
    payload = PREFIX + command.encode("ascii") + SUFFIX
    return HEADER + struct.pack(">IIB3s", 16, len(payload), 1, b"\x00\x00\x00") + payload


# TCP is a byte stream: headers and payloads can arrive in fragments. Read
# the declared lengths, enforce a timeout, and reject oversized packets.
async def read_packet(reader: asyncio.StreamReader, timeout: float = 2.0) -> Optional[str]:
    """Read one eISCP packet (or return None if no reply is sent)."""
    try:
        async with asyncio.timeout(timeout):
            header = await reader.readexactly(16)
            if header[:4] != HEADER:
                raise ValueError("Receiver returned an invalid eISCP header")
            data_length = struct.unpack(">I", header[8:12])[0]
            if not 0 < data_length <= 65536:
                raise ValueError("Invalid eISCP response length")
            payload = await reader.readexactly(data_length)
        return payload.decode("ascii", errors="replace").strip("\x00\r\n\x1a")
    except (asyncio.TimeoutError, asyncio.IncompleteReadError):
        return None


# Open a short-lived connection for each command. Actions only wait for
# their bytes to be sent; queries ignore unrelated messages until a matching
# response arrives or their deadline expires. Always close the socket.
async def send_command(
    host: str, port: int, command: str, timeout: float = 3.0,
    *, expect_response: bool = True,
) -> Optional[str]:
    """Send eISCP; fire-and-forget actions must not wait for an ACK.

    Queries wait for a response matching the requested three-letter command prefix;
    unsolicited status packets are skipped.
    """
    # Reject invalid commands before opening a socket.
    packet = encode_packet(command)
    client = CLIENTS.get((host, port))
    if client is not None:
        return await client.send(command, packet, timeout, expect_response)
    reader = writer = None
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(host, port)
        writer.write(packet)
        async with asyncio.timeout(timeout):
            await writer.drain()
        if not expect_response:
            return None
        expected = command[:3].upper()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (remaining := deadline - loop.time()) > 0:
            response = await read_packet(reader, timeout=remaining)
            if response is None:
                break
            payload = response.removeprefix("!1")
            if payload.startswith(expected):
                return payload
        return None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass


def extract_nms_identifier(response: Optional[str]) -> tuple[Optional[str], str]:
    """Decode NMS S1xx network-service marker (e.g. NMSxxxxxS10a -> 0A)."""
    if not response:
        return None, "No response received from NMSQSTN."
    payload = response.strip().removeprefix("!1")
    if not payload.startswith("NMS"):
        return None, f"Unexpected response command: {payload[:12]!r}"
    match = re.search(r"S1([0-9A-Fa-f]{2})(?:$|[^0-9A-Fa-f])", payload)
    if not match:
        return None, f"NMS response lacks an S1xx service marker: {payload!r}"
    return match.group(1).upper(), payload
