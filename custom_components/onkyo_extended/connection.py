"""One paced TCP connection shared by every entity for a receiver.

The old implementation opened a socket for each action/query. A competing
client could evict it, and a new socket could receive an old startup status.
Here one reader processes all messages in order, including remote-control
changes. A single send lock prevents command bursts from our own entities.
"""
from __future__ import annotations

import asyncio
import logging
import struct

_LOGGER = logging.getLogger(__name__)


class ReceiverConnection:
    def __init__(self, host, port, task_factory, *, pacing=1.0):
        self.host, self.port = host, port
        self.task_factory, self.pacing = task_factory, pacing
        self.on_message = None
        self.on_connection = None
        self._ready = asyncio.Event()
        self._lock = asyncio.Lock()
        self._writer = None
        self._pending = None
        self._task = None
        self._closing = False
        self._last_send = 0.0

    @property
    def connected(self):
        return self._ready.is_set()

    def start(self):
        self._task = self.task_factory(self._run(), "Onkyo Extended receiver connection")

    async def close(self):
        """Stop reconnecting and cancel the reader when HA unloads the entry."""
        self._closing = True
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self):
        retry = 1
        while not self._closing:
            writer = None
            try:
                async with asyncio.timeout(5):
                    reader, writer = await asyncio.open_connection(self.host, self.port)
                self._writer = writer
                # Quiet settling time before publishing connected avoids putting
                # a query ahead of the receiver's initial connection messages.
                await asyncio.sleep(0.5)
                self._ready.set()
                if self.on_connection:
                    self.on_connection(True)
                retry = 1
                while True:
                    header = await reader.readexactly(16)
                    if header[:4] != b"ISCP":
                        raise ValueError("Invalid eISCP header")
                    header_size, length = struct.unpack(">II", header[4:12])
                    if not 16 <= header_size <= 64 or not 0 < length <= 65536:
                        raise ValueError("Invalid eISCP packet length")
                    if header_size > 16:
                        await reader.readexactly(header_size - 16)
                    data = await reader.readexactly(length)
                    message = data.decode("utf-8", errors="replace").strip("\x00\r\n\x1a")
                    if not message.startswith("!1"):
                        continue
                    message = message[2:]
                    # Cache/publish the reply even if nobody is waiting for it.
                    # That is what makes physical-remote changes appear in HA.
                    if self.on_message:
                        try:
                            self.on_message(message)
                        except Exception:
                            _LOGGER.exception("Could not decode receiver status")
                    pending = self._pending
                    if pending and message.startswith(pending[0]) and not pending[1].done():
                        pending[1].set_result(message)
            except (OSError, ValueError, asyncio.IncompleteReadError, TimeoutError) as err:
                _LOGGER.debug("Receiver connection lost; retrying in %s s: %s", retry, err)
            finally:
                self._ready.clear()
                self._writer = None
                if self._pending and not self._pending[1].done():
                    self._pending[1].set_exception(ConnectionError("Receiver disconnected"))
                if self.on_connection:
                    self.on_connection(False)
                if writer:
                    writer.close()
                    try:
                        async with asyncio.timeout(2):
                            await writer.wait_closed()
                    except (OSError, TimeoutError):
                        pass
            if not self._closing:
                await asyncio.sleep(retry)
                retry = min(30, retry * 2)

    async def send(self, command, packet, timeout, expect_response):
        """Never automatically repeat an action: repeating volume-up is unsafe."""
        async with self._lock:
            async with asyncio.timeout(timeout):
                await self._ready.wait()
                loop = asyncio.get_running_loop()
                await asyncio.sleep(max(0, self.pacing - (loop.time() - self._last_send)))
                writer = self._writer
                if writer is None:
                    raise ConnectionError("Receiver is reconnecting")
                future = loop.create_future() if expect_response else None
                self._pending = (command[:3], future) if future else None
                try:
                    writer.write(packet)
                    self._last_send = loop.time()
                    await writer.drain()
                    return await future if future else None
                finally:
                    self._pending = None
