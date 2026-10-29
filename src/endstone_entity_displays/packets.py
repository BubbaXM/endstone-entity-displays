"""Stationary native block visuals, Bedrock protocols 2193 and 2225.

Wire layout: EndstoneMC/bedrock-protocol protocol/actor.py (AddActorPacket,
DataItemEntry, DataItem*Payload). FallingBlock VARIANT is its network block
runtime ID, as in PocketMine-MP src/entity/object/FallingBlock.php.
Never spawn a real falling block: that would fall, expire or place a block.
"""
import math
import struct

SUPPORTED_PROTOCOLS = frozenset({2193, 2225})
ADD_ACTOR, REMOVE_ACTOR, MOVE_ACTOR, SET_ACTOR_DATA, SYNC_ACTOR_PROPERTY = 13, 14, 18, 39, 165


def uint(value):
    if type(value) is not int or not 0 <= value < 1 << 64:
        raise ValueError("Unsigned packet integer out of range.")
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def sint(value, bits=32):
    if type(value) is not int or not -(1 << (bits - 1)) <= value < 1 << (bits - 1):
        raise ValueError("Signed packet integer out of range.")
    return uint((value << 1) ^ (value >> (bits - 1)))


def string(value):
    data = value.encode("utf-8")
    return uint(len(data)) + data


def block_variant(value):
    # Some servers use signed IDs; hashed block palettes may expose uint32.
    if type(value) is not int or not -(1 << 31) <= value < 1 << 32:
        raise ValueError("Invalid native block runtime ID.")
    return value - (1 << 32) if value >= 1 << 31 else value


def metadata(block_runtime_id, scale=1.0):
    # Protocol 2168+ encodes BOTH the variant index and the payload type.
    flags = (1 << 16) | (1 << 17) | (1 << 50)  # NOAI, SILENT, FIRE_IMMUNE
    entries = [uint(0) + b"\x07\x07" + sint(flags, 64),
               uint(2) + b"\x02\x02" + sint(block_variant(block_runtime_id)),
               uint(38) + b"\x03\x03" + struct.pack("<f", scale),
               uint(53) + b"\x03\x03" + struct.pack("<f", 0.0),
               uint(54) + b"\x03\x03" + struct.pack("<f", 0.0)]
    # HAS_GRAVITY, HAS_COLLISION, INVISIBLE and name-tag flags are not set.
    return uint(len(entries)) + b"".join(entries)


def passenger_tail(protocol):
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"Unsupported display protocol {protocol}")
    # 26.60 appends optional PassengerOfBlockArguments after the actor links.
    return b"\x00" if protocol == 2225 else b""


def add_block(unique_id, runtime_id, position, block_runtime_id, protocol=2193):
    if len(position) != 3 or not all(math.isfinite(v) for v in position):
        raise ValueError("Invalid block display position.")
    x, bottom, z = position
    # FallingBlock's network origin is the visual centre, unlike our legacy
    # custom entity's bottom centre. Keep placement and picking in bottom coords.
    return (sint(unique_id, 64) + uint(runtime_id) + string("minecraft:falling_block") +
            struct.pack("<10f", x, bottom + .5, z, 0, 0, 0, 0, 0, 0, 0) +
            b"\x00" + metadata(block_runtime_id) + b"\x00\x00\x00" + passenger_tail(protocol))


def remove_block(unique_id):
    # RemoveActor takes the signed UNIQUE id, not the runtime id.
    return sint(unique_id, 64)


def properties(values):
    return uint(len(values)) + b"".join(uint(i) + sint(v) for i, v in values) + b"\x00"


def schema(actor_type, definitions):
    def tag(kind, name, payload):
        return bytes([kind]) + string(name) + payload
    entries = []
    for name, definition in definitions.items():
        low, high = definition["range"]
        entries.append(tag(8, "name", string(name)) + tag(3, "type", sint(0)) +
                       tag(3, "min", sint(low)) + tag(3, "max", sint(high)) + b"\x00")
    return (b"\x0a\x00" + tag(8, "type", string(actor_type)) +
            tag(9, "properties", b"\x0a" + sint(len(entries)) + b"".join(entries)) + b"\x00")


def add_visual(unique_id, runtime_id, display, variant, protocol=2193):
    from .catalog import actor_type, values
    from .transforms import centre
    custom = display.mode != "native"
    kind = actor_type(display)
    return (sint(unique_id, 64) + uint(runtime_id) + string(kind) +
            struct.pack("<10f", *centre(display.position, display.size), 0, 0, 0, 0, 0, 0, 0) +
            b"\x00" + metadata(variant, 1.0 if custom else display.size[0]) +
            properties(values(display) if custom else []) + b"\x00" + passenger_tail(protocol))


def move_visual(runtime_id, display):
    # Mojang MoveActorAbsoluteData: runtime, header byte, Vec3, three angle bytes.
    # Keep actor rotation zero: cuboid rotation is applied on the model bones.
    from .transforms import centre
    return uint(runtime_id) + b"\x02" + struct.pack("<3f", *centre(display.position, display.size)) + b"\x00\x00\x00"


def update_visual(runtime_id, display, variant):
    from .catalog import values
    custom = display.mode != "native"
    return (uint(runtime_id) + metadata(variant, 1.0 if custom else display.size[0]) +
            properties(values(display) if custom else []) + b"\x00")
