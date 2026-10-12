"""A small reader for Garmin FIT files, enough for the golf scorecard files of the Garmin data export.

A FIT file is a header, a stream of *definition* messages (which fields a message has, how large they are) and
*data* messages (the values), and a checksum. Only what is needed is implemented: the numbers and strings of
ordinary and compressed-timestamp messages. Developer fields are skipped, the checksum is not verified, and
nothing in the file is changed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

# base type number (low 5 bits of the type byte) -> (struct code, size in bytes)
_BASE_TYPES = {
    0: ("B", 1), 1: ("b", 1), 2: ("B", 1), 3: ("h", 2), 4: ("H", 2), 5: ("i", 4), 6: ("I", 4),
    8: ("f", 4), 9: ("d", 8), 10: ("B", 1), 11: ("H", 2), 12: ("I", 4), 13: ("B", 1),
    14: ("q", 8), 15: ("Q", 8), 16: ("Q", 8),
}
_STRING = 7


@dataclass(frozen=True)
class Message:
    number: int                     # the global message number (what kind of message this is)
    fields: Dict[int, object]       # field number -> value (an int or float, a str, or a tuple for an array)


def _value(raw: bytes, base: int, endian: str):
    if base == _STRING:
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    code, size = _BASE_TYPES.get(base, ("B", 1))
    if len(raw) == size:
        return struct.unpack(endian + code, raw)[0]
    count = len(raw) // size
    return tuple(struct.unpack(endian + code, raw[i * size:(i + 1) * size])[0] for i in range(count))


def read_fit(path) -> List[Message]:
    """All data messages of a FIT file, in file order."""
    data = Path(path).read_bytes()
    if len(data) < 14 or data[8:12] != b".FIT":
        raise ValueError(f"{path} is not a FIT file")
    header_size = data[0]
    end = header_size + struct.unpack("<I", data[4:8])[0]
    end = min(end, len(data))
    pos = header_size
    definitions: Dict[int, Tuple[str, int, List[Tuple[int, int, int]]]] = {}
    messages: List[Message] = []
    while pos < end:
        header = data[pos]
        pos += 1
        if header & 0x80:                                      # compressed timestamp header: a data message
            local = (header >> 5) & 0x03
        elif header & 0x40:                                    # definition message
            local = header & 0x0F
            endian = ">" if data[pos + 1] else "<"
            number = struct.unpack(endian + "H", data[pos + 2:pos + 4])[0]
            count = data[pos + 4]
            fields = [tuple(data[pos + 5 + 3 * i:pos + 8 + 3 * i]) for i in range(count)]
            pos += 5 + 3 * count
            if header & 0x20:                                  # developer fields: only their size matters
                dev_count = data[pos]
                dev = [tuple(data[pos + 1 + 3 * i:pos + 4 + 3 * i]) for i in range(dev_count)]
                pos += 1 + 3 * dev_count
                fields += [(-1 - i, size, 0xFF) for i, (_, size, _) in enumerate(dev)]
            definitions[local] = (endian, number, fields)
            continue
        else:
            local = header & 0x0F
        if local not in definitions:
            raise ValueError(f"{path}: data message with an undefined type at byte {pos - 1}")
        endian, number, fields = definitions[local]
        values: Dict[int, object] = {}
        for field, size, base_type in fields:
            raw = data[pos:pos + size]
            pos += size
            if field >= 0:
                values[field] = _value(raw, base_type & 0x1F, endian)
        messages.append(Message(number, values))
    return messages
