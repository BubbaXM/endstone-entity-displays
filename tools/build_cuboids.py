"""Generate textured cuboid render assets; references vanilla textures, no PNG copying.

Inputs: this server's shipped vanilla blocks.json overlays and a cached copy of
Mojang's public terrain_texture.json. --refresh fetches only that official file.
Outputs are generated JSON, never hand-edited. Custom texture mappings may be
added in tools/cuboid_overrides.json and require their own installed RP.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/textures/terrain_texture.json"
FACES = ("north", "south", "east", "west", "up", "down")
PROPERTIES = {**{f"ed:{axis}": {"type": "int", "range": [50, 32000], "default": 1000, "client_sync": True}
                 for axis in ("w", "h", "d")},
              **{f"ed:{axis}": {"type": "int", "range": [-180000, 180000], "default": 0, "client_sync": True}
                 for axis in ("rx", "ry", "rz")}}


def parse_jsonc(raw):
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    # Preserve quoted paths/URLs; remove only JSONC comments outside strings.
    pattern = r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/'
    return json.loads(re.sub(pattern, lambda m: m.group() if m.group().startswith('"') else '', text))


def write(relative, data):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")


def texture_path(value):
    if isinstance(value, list):
        return texture_path(value[0]) if value else None
    if isinstance(value, dict):
        return texture_path(value.get("path", value.get("variations", [])))
    if isinstance(value, str) and re.fullmatch(r"textures/[a-zA-Z0-9_./-]+", value) and ".." not in value:
        return value
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--server", type=Path, default=ROOT.parent / "bedrock_server")
    args = parser.parse_args()
    cache = ROOT / "tools/data/terrain_texture.json"
    if args.refresh:
        with urllib.request.urlopen(URL, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024)
        parse_jsonc(raw)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(raw)
    terrain = parse_jsonc(cache.read_bytes())["texture_data"]
    folders = [args.server / "resource_packs/vanilla"]
    overlays = [p for p in (args.server / "resource_packs").glob("vanilla_*")
                if re.fullmatch(r"vanilla_[0-9.]+", p.name)]
    folders += sorted(overlays, key=lambda p: tuple(int(n) for n in p.name.split("_", 1)[1].split(".")))
    definitions = {}
    for folder in folders:
        path = folder / "blocks.json"
        if path.is_file():
            for name, definition in parse_jsonc(path.read_bytes()).items():
                if name != "format_version" and isinstance(definition, dict):
                    definitions.setdefault(name, {}).update(definition)
    blocks = {}
    for name, definition in definitions.items():
        textures = definition.get("carried_textures", definition.get("textures"))
        if isinstance(textures, str):
            textures = {face: textures for face in FACES}
        if not isinstance(textures, dict):
            continue
        faces = {}
        for face in FACES:
            alias = textures.get(face, textures.get("side"))
            entry = terrain.get(alias, {}) if isinstance(alias, str) else {}
            path = texture_path(entry.get("textures"))
            if not path:
                break
            faces[face] = path
        if len(faces) == 6:
            blocks[name if ":" in name else "minecraft:" + name] = faces
    overrides = ROOT / "tools/cuboid_overrides.json"
    if overrides.is_file():
        for name, faces in json.loads(overrides.read_text(encoding="utf-8")).items():
            if isinstance(faces, str):
                faces = {face: faces for face in FACES}
            if set(faces) != set(FACES) or not all(texture_path(p) == p for p in faces.values()):
                raise ValueError(f"Invalid custom cuboid mapping: {name}")
            blocks[name] = faces
    assert "minecraft:oak_planks" in blocks and "minecraft:stone" in blocks
    names = sorted(blocks)
    paths = sorted({p for faces in blocks.values() for p in faces.values()})
    aliases = {p: f"t{i}" for i, p in enumerate(paths)}
    source = {"url": URL, "sha256": hashlib.sha256(cache.read_bytes()).hexdigest()}
    write("resource_pack/ed_catalog.json", {"version": 1, "blocks": names, "source": source})
    original = json.loads((ROOT / "behavior_pack/entities/oak_planks.json").read_text())
    original["minecraft:entity"]["description"]["identifier"] = "ed:cuboid"
    original["minecraft:entity"]["description"]["properties"] = PROPERTIES
    original["minecraft:entity"]["components"]["minecraft:variant"] = {"value": 0}
    write("behavior_pack/entities/cuboid.json", original)
    geometry, controllers = [], {}
    for face in FACES:
        geometry.append({"description": {"identifier": f"geometry.ed.cuboid_{face}", "texture_width": 16,
                                         "texture_height": 16, "visible_bounds_width": 112,
                                         "visible_bounds_height": 112, "visible_bounds_offset": [0, 0, 0]},
                         "bones": [{"name": "yaw", "pivot": [0, 0, 0]},
                                   {"name": "pitch", "parent": "yaw", "pivot": [0, 0, 0]},
                                   {"name": "roll", "parent": "pitch", "pivot": [0, 0, 0]},
                                   {"name": "box", "parent": "roll", "pivot": [0, 0, 0],
                                    "cubes": [{"origin": [-8, -8, -8], "size": [16, 16, 16],
                                               "uv": {face: {"uv": [0, 0], "uv_size": [16, 16]}}}]}]})
        materials = ["Material.blend" if any(t in name for t in ("glass", "ice", "slime", "honey")) else "Material.default" for name in names]
        controllers[f"controller.render.ed.cuboid_{face}"] = {
            "arrays": {"textures": {"Array.face": ["Texture." + aliases[blocks[name][face]] for name in names]},
                       "materials": {"Array.surface": materials}},
            "geometry": "Geometry." + face, "materials": [{"*": "Array.surface[query.variant]"}],
            "textures": ["Array.face[query.variant]"]}
    write("resource_pack/models/entity/cuboid.geo.json", {"format_version": "1.12.0", "minecraft:geometry": geometry})
    write("resource_pack/render_controllers/cuboid.render_controllers.json", {"format_version": "1.8.0", "render_controllers": controllers})
    write("resource_pack/entity/cuboid.entity.json", {"format_version": "1.10.0", "minecraft:client_entity": {"description": {
        "identifier": "ed:cuboid", "materials": {"default": "entity_alphatest", "blend": "entity_alphablend"},
        "textures": {aliases[path]: path for path in paths},
        "geometry": {face: f"geometry.ed.cuboid_{face}" for face in FACES},
        "animations": {"transform": "animation.ed.cuboid_transform"}, "scripts": {"animate": ["transform"]},
        "render_controllers": [f"controller.render.ed.cuboid_{face}" for face in FACES]}}})
    write("resource_pack/animations/cuboid.animation.json", {"format_version": "1.8.0", "animations": {
        "animation.ed.cuboid_transform": {"loop": True, "bones": {
            "yaw": {"rotation": [0, "query.property('ed:ry') / 1000", 0]},
            "pitch": {"rotation": ["query.property('ed:rx') / 1000", 0, 0]},
            "roll": {"rotation": [0, 0, "query.property('ed:rz') / 1000"]},
            "box": {"scale": [f"query.property('ed:{axis}') / 1000" for axis in ("w", "h", "d")]}}}}})
    print(f"Built cuboid transforms for {len(names)} block texture mappings ({len(paths)} referenced vanilla textures).")


if __name__ == "__main__":
    main()
