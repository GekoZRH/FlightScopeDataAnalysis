"""Build small FIT files for the tests (the real ones are personal data)."""

import struct

# type name -> (base type number, struct code, size)
TYPES = {
    "enum": (0, "B", 1), "sint8": (1, "b", 1), "uint8": (2, "B", 1), "sint16": (3, "h", 2), "uint16": (4, "H", 2),
    "sint32": (5, "i", 4), "uint32": (6, "I", 4),
}


def _definition(number, fields, local, big, developer=()):
    endian = ">" if big else "<"
    header = 0x40 | local | (0x20 if developer else 0)
    out = struct.pack("BBB", header, 0, 1 if big else 0) + struct.pack(endian + "H", number) + bytes([len(fields)])
    for field_number, kind, value in fields:
        if kind == "string":
            out += bytes([field_number, len(value), 7])
        elif kind.startswith("array:"):
            base, _, count = kind.split(":")[1], None, len(value)
            out += bytes([field_number, TYPES[base][2] * count, TYPES[base][0]])
        else:
            out += bytes([field_number, TYPES[kind][2], TYPES[kind][0]])
    if developer:
        out += bytes([len(developer)]) + b"".join(bytes([n, size, 0]) for n, size in developer)
    return out


def _data(fields, local, big, developer=()):
    endian = ">" if big else "<"
    out = bytes([local])
    for _, kind, value in fields:
        if kind == "string":
            out += value
        elif kind.startswith("array:"):
            base = kind.split(":")[1]
            out += b"".join(struct.pack(endian + TYPES[base][1], v) for v in value)
        else:
            out += struct.pack(endian + TYPES[kind][1], value)
    for _, size in developer:
        out += b"\xAA" * size
    return out


def message(number, fields, local=0, big=False, developer=()):
    """A definition and a data message. `fields` is a list of (field number, type name, value); a string value is bytes."""
    return _definition(number, fields, local, big, developer) + _data(fields, local, big, developer)


def data_only(fields, local=0, big=False):
    """A further data message of an already defined type."""
    return _data(fields, local, big)


def fit_file(*chunks, header_size=14):
    body = b"".join(chunks)
    header = struct.pack("<BBHI4s", header_size, 0x20, 2000, len(body), b".FIT")
    if header_size == 14:
        header += b"\x00\x00"
    return header + body + b"\x00\x00"


def golf_fit(course, holes):
    """A golf scorecard file: the course (message 190) and one message 193 per hole (number, par, stroke index)."""
    chunks = [message(190, [(0, "uint32", 28390), (1, "string", course.encode("utf-8").ljust(40, b"\x00"))])]
    for number, (par, index) in enumerate(holes, start=1):
        chunks.append(message(193, [(0, "uint8", number), (1, "uint16", 40000), (2, "uint8", par), (3, "uint8", index)], local=1) if number == 1
                      else data_only([(0, "uint8", number), (1, "uint16", 40000), (2, "uint8", par), (3, "uint8", index)], local=1))
    return fit_file(*chunks)
