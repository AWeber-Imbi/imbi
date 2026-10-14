"""The runner to executor socket (plan section 6.1).

One request per connection: a JSON line from the runner, then a JSON
line from the executor. When the runner closes the connection first,
the executor stops the work of that request.
"""

import asyncio
import json
import socket
import struct
import sys
import typing

SOCKET_DIR = '/run/executor'
SOCKET_PATH = f'{SOCKET_DIR}/executor.sock'
#: The largest request or reply line.
LIMIT = 4 * 1024 * 1024

type Message = dict[str, typing.Any]


def peer_uid(sock: socket.socket) -> int:
    """Return the uid of the peer of a unix socket (Linux only)."""
    if sys.platform != 'linux':  # pragma: no cover
        raise OSError('SO_PEERCRED needs Linux')
    creds = sock.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')
    )
    _pid, uid, _gid = struct.unpack('3i', creds)
    return uid


async def read(reader: asyncio.StreamReader) -> Message | None:
    """Read one message, or ``None`` at the end of the stream."""
    line = await reader.readline()
    if not line:
        return None
    value = json.loads(line)
    if not isinstance(value, dict):
        raise TypeError('A message is a JSON object')
    return typing.cast('Message', value)


async def write(writer: asyncio.StreamWriter, message: Message) -> None:
    writer.write(json.dumps(message).encode() + b'\n')
    await writer.drain()


async def call(message: Message, path: str = SOCKET_PATH) -> Message:
    """Send one request to the executor and return its reply."""
    reader, writer = await asyncio.open_unix_connection(path, limit=LIMIT)
    try:
        await write(writer, message)
        reply = await read(reader)
    finally:
        writer.close()
    if reply is None:
        raise ConnectionError('The executor closed the connection')
    return reply
