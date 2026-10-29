"""Generated client-side texture choices and property ordering."""
import json

from .packs import bundled_files

CUBOID_TYPE = "ed:cuboid"
MODEL_TYPE = "ed:model"
PROPERTIES = {**{f"ed:{axis}": {"range": [50, 32000], "default": 1000} for axis in ("w", "h", "d")},
              **{f"ed:{axis}": {"range": [-180000, 180000], "default": 0} for axis in ("rx", "ry", "rz")}}


def load_catalog():
    data = json.loads(bundled_files()["resource_pack/ed_catalog.json"])
    names = data["blocks"]
    if data.get("version") != 1 or not isinstance(names, list) or len(names) != len(set(names)) or len(names) > 8192:
        raise ValueError("Invalid bundled cuboid texture catalog.")
    return {name: index for index, name in enumerate(names)}


def load_models():
    from .store import block_id
    from .transforms import size_vector
    data = json.loads(bundled_files()["resource_pack/ed_models.json"])
    if data.get("version") != 1 or not isinstance(data.get("blocks"), list) or len(data["blocks"]) > 8192:
        raise ValueError("Invalid bundled model catalog.")
    result = {}
    for index, entry in enumerate(data["blocks"]):
        name = block_id(entry["block"])
        if name in result or entry["kind"] not in {"door", "chest"}:
            raise ValueError("Duplicate or invalid display model.")
        result[name] = (index, size_vector(entry["size"]))
    return result


def actor_type(display):
    return {"native": "minecraft:falling_block", "cuboid": CUBOID_TYPE, "model": MODEL_TYPE}[display.mode]


def values(display):
    return [(index, round(value * 1000)) for index, value in enumerate((*display.size, *display.rotation))]
