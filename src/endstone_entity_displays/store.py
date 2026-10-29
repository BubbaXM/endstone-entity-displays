"""Validated block IDs and atomic display persistence; no native actor objects."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .transforms import centre, half_extents, rotation_vector, size_vector

BLOCK_ID = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+", re.ASCII)
INVISIBLE = frozenset({"minecraft:air", "minecraft:cave_air", "minecraft:void_air",
                       "minecraft:structure_void", "minecraft:invisible_bedrock"})
BOUNDS = {0: (-64, 320), 1: (0, 128), 2: (0, 256)}
MAX_DISPLAYS = 10000


def block_id(value):
    if not isinstance(value, str) or len(value) > 128 or not BLOCK_ID.fullmatch(value):
        raise ValueError("Use a namespaced block ID, for example minecraft:stone.")
    if value in INVISIBLE:
        raise ValueError("That block has no visible display. Choose a visible block.")
    return value


@dataclass(frozen=True)
class Display:
    id: str
    block: str
    dimension: int
    position: tuple
    size: tuple = (1.0, 1.0, 1.0)
    rotation: tuple = (0.0, 0.0, 0.0)
    mode: str = "native"
    persistent: bool = True

    def encode(self):
        return {"id": self.id, "block": self.block, "dimension": self.dimension,
                "position": list(self.position), "size": list(self.size), "rotation": list(self.rotation),
                "mode": self.mode, "persistent": self.persistent}


def validate_record(record):
    original = {"id", "block", "dimension", "position"}
    if not isinstance(record, dict) or not original <= set(record) or set(record) - original - {"size", "rotation", "mode", "persistent"}:
        raise ValueError("Invalid saved display record.")
    key, dimension, position = record["id"], record["dimension"], record["position"]
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
        raise ValueError("Invalid saved display ID.")
    if type(dimension) is not int or dimension not in BOUNDS:
        raise ValueError("Unsupported display dimension.")
    if not isinstance(position, (tuple, list)) or len(position) != 3 or not all(
            type(v) in (int, float) and math.isfinite(v) for v in position):
        raise ValueError("Invalid saved display position.")
    size = size_vector(record.get("size", (1, 1, 1)))
    rotation = rotation_vector(record.get("rotation", (0, 0, 0)))
    mode, persistent = record.get("mode", "native"), record.get("persistent", True)
    if not isinstance(mode, str) or mode not in {"native", "cuboid", "model"} or type(persistent) is not bool:
        raise ValueError("Invalid display render mode or persistence flag.")
    if mode == "native" and (size != (1.0, 1.0, 1.0) or any(rotation)):
        raise ValueError("Native mode preserves the original unit block; use auto, cuboid or model for visual resizing/rotation.")
    x, y, z = centre(position, size)
    ex, ey, ez = half_extents(size, rotation)
    low, high = BOUNDS[dimension]
    if y - ey < low - 1e-6 or y + ey > high + 1e-6 or max(abs(x) + ex, abs(z) + ez) > 29_999_980:
        raise ValueError("Display position is outside the supported world bounds.")
    return Display(key, block_id(record["block"]), dimension, tuple(position), size, rotation, mode, persistent)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key in display storage; original file preserved.")
        result[key] = value
    return result


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.displays, self.revision = {}, 0
        self.check_path()
        if self.path.exists():
            if self.path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Display storage is too large; original file preserved.")
            data = json.loads(self.path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
            if not isinstance(data, dict) or set(data) != {"version", "displays"} or type(data["version"]) is not int or data["version"] not in (1, 2):
                raise ValueError("Unsupported display storage; original file preserved.")
            self.displays = self.validated(data["displays"])

    def check_path(self):
        # Never follow a linked file/directory into another plugin or world.
        for path in (self.path, *self.path.parents):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError("Refusing linked display storage.")

    @staticmethod
    def validated(records):
        if not isinstance(records, list) or len(records) > MAX_DISPLAYS:
            raise ValueError(f"Display storage must contain at most {MAX_DISPLAYS} displays.")
        result = {}
        for record in records:
            display = validate_record(record)
            if display.id in result:
                raise ValueError("Duplicate display ID; original storage preserved.")
            result[display.id] = display
        return result

    def commit(self, displays, save=True):
        validated = self.validated([display.encode() for display in displays.values()])
        if not save:
            self.displays = validated
            self.revision += 1
            return
        data = (json.dumps({"version": 2, "displays": [d.encode() for d in validated.values() if d.persistent]},
                           indent=2, allow_nan=False) + "\n").encode("utf-8")
        self.check_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".ed-save-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)  # Only this invocation's exact temporary file.
        # Failed writes never change the active display list.
        self.displays = validated
        self.revision += 1

    def add(self, block, dimension, position):
        display = validate_record({"id": uuid4().hex, "block": block, "dimension": dimension,
                                   "position": position})
        replacement = dict(self.displays)
        replacement[display.id] = display
        self.commit(replacement)
        return display

    def put(self, display, save=True):
        if not save:
            # Animation frames validate one record and update the spatial-index
            # revision, not re-validate/serialize every display on the server.
            display = validate_record(display.encode())
            if display.id not in self.displays and len(self.displays) >= MAX_DISPLAYS:
                raise ValueError(f"At most {MAX_DISPLAYS} displays are supported.")
            self.displays[display.id] = display
            self.revision += 1
            return
        replacement = dict(self.displays)
        replacement[display.id] = display
        self.commit(replacement)

    def remove(self, key, save=True):
        if key not in self.displays:
            raise ValueError("Display no longer exists.")
        if not save:
            del self.displays[key]
            self.revision += 1
            return
        replacement = dict(self.displays)
        del replacement[key]
        if save:
            self.commit(replacement)
        else:
            self.commit(replacement, save=False)
