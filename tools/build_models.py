"""Generate closed chest/full door display models, referencing vanilla textures.

No block entities, inventories, state simulation, copied PNGs or per-tick work.
Geometry is normalized to a unit box; the six existing transform properties
therefore continue to describe the actual visual dimensions, not hitbox size.
"""
import json

from build_cuboids import ROOT, PROPERTIES, parse_jsonc, texture_path, write


def bones(cubes):
    return [{"name": "yaw", "pivot": [0, 0, 0]},
            {"name": "pitch", "parent": "yaw", "pivot": [0, 0, 0]},
            {"name": "roll", "parent": "pitch", "pivot": [0, 0, 0]},
            {"name": "box", "parent": "roll", "pivot": [0, 0, 0], **({"cubes": cubes} if cubes else {})}]


def geometry(name, cubes, atlas=16):
    return {"description": {"identifier": "geometry.ed." + name, "texture_width": atlas,
                            "texture_height": atlas, "visible_bounds_width": 112,
                            "visible_bounds_height": 112, "visible_bounds_offset": [0, 0, 0]},
            "bones": bones(cubes)}


def box_uv(u, v, w, h, d):
    return {face: {"uv": uv, "uv_size": size} for face, uv, size in (
        ("west", [u, v + d], [d, h]), ("north", [u + d, v + d], [w, h]),
        ("east", [u + d + w, v + d], [d, h]), ("south", [u + d * 2 + w, v + d], [w, h]),
        ("up", [u + d, v], [w, d]), ("down", [u + d + w, v + d], [w, -d]))}


def chest_cube(origin, size, uv):
    # Actual chest bounds: X -7..7, Y -7..7, Z -8..7 (including latch).
    return {"origin": [origin[0] * 16 / 14, origin[1] * 16 / 14, (origin[2] + .5) * 16 / 15],
            "size": [size[0] * 16 / 14, size[1] * 16 / 14, size[2] * 16 / 15], "uv": uv}


def main():
    terrain = parse_jsonc((ROOT / "tools/data/terrain_texture.json").read_bytes())["texture_data"]
    models = {}
    # The old seven door species share an indexed atlas alias, not index zero
    # for every species (the generic cuboid generator cannot infer this).
    lower, upper = terrain["door_lower"]["textures"], terrain["door_upper"]["textures"]
    for index, name in enumerate(("wooden", "spruce", "birch", "jungle", "acacia", "dark_oak", "iron")):
        models["minecraft:" + name + "_door"] = {
            "kind": "door", "size": [1, 2, .188], "textures": [lower[index], upper[index]]}
    models["minecraft:oak_door"] = models["minecraft:wooden_door"]
    for name in ("crimson", "warped", "mangrove", "bamboo", "cherry", "pale_oak", "poplar",
                 "copper", "exposed_copper", "weathered_copper", "oxidized_copper"):
        bottom = name + ("_door_lower" if name in ("crimson", "warped") else "_door_bottom")
        top = name + "_door_top"
        if bottom not in terrain or top not in terrain:
            continue
        textures = [texture_path(terrain[key]["textures"]) for key in (bottom, top)]
        assert all(textures)
        entry = {"kind": "door", "size": [1, 2, .188], "textures": textures}
        models["minecraft:" + name + "_door"] = entry
        if "copper" in name:
            models["minecraft:waxed_" + name + "_door"] = entry
    for name, atlas in (("chest", "normal"), ("trapped_chest", "trapped"), ("ender_chest", "ender")):
        path = "textures/entity/chest/" + atlas
        models["minecraft:" + name] = {"kind": "chest", "size": [.875, .875, .938], "textures": [path, path]}
    for prefix, atlas in (("", "default"), ("exposed_", "exposed"), ("weathered_", "weathered"), ("oxidized_", "oxidized")):
        path = "textures/entity/chest/copper_" + atlas
        entry = {"kind": "chest", "size": [.875, .875, .938], "textures": [path, path]}
        for wax in ("", "waxed_"):
            models["minecraft:" + wax + prefix + "copper_chest"] = entry
    names = sorted(models)
    write("resource_pack/ed_models.json", {"version": 1, "blocks": [{"block": name, **models[name]} for name in names]})
    bp = json.loads((ROOT / "behavior_pack/entities/cuboid.json").read_text())
    bp["minecraft:entity"]["description"]["identifier"] = "ed:model"
    bp["minecraft:entity"]["description"]["properties"] = PROPERTIES
    write("behavior_pack/entities/model.json", bp)
    # Thin two-block door. The upper and lower textures each cover one half;
    # edge UVs sample only three texels rather than stretching a full face.
    door_uv = {"north": {"uv": [0, 0], "uv_size": [16, 16]},
               "south": {"uv": [16, 0], "uv_size": [-16, 16]},
               "west": {"uv": [0, 0], "uv_size": [3, 16]},
               "east": {"uv": [13, 0], "uv_size": [3, 16]},
               "up": {"uv": [0, 0], "uv_size": [16, 3]},
               "down": {"uv": [0, 13], "uv_size": [16, 3]}}
    # Trim the body under the closed lid instead of overlapping coplanar side
    # faces, avoiding z-fighting. UVs retain the original 64x64 chest layout.
    base_uv = box_uv(0, 19, 14, 10, 14)
    for face in ("north", "south", "east", "west"):
        base_uv[face]["uv"][1] += 1
        base_uv[face]["uv_size"][1] -= 1
    cubes = [chest_cube([-7, -7, -7], [14, 9, 14], base_uv),
             chest_cube([-7, 2, -7], [14, 5, 14], box_uv(0, 0, 14, 5, 14)),
             chest_cube([-1, 0, -8], [2, 4, 1], box_uv(0, 0, 2, 4, 1))]
    geometries = [geometry("chest", cubes, 64), geometry("empty", []),
                  geometry("door_lower", [{"origin": [-8, -8, -8], "size": [16, 8, 16], "uv": door_uv}]),
                  geometry("door_upper", [{"origin": [-8, 0, -8], "size": [16, 8, 16], "uv": door_uv}])]
    write("resource_pack/models/entity/model.geo.json", {"format_version": "1.12.0", "minecraft:geometry": geometries})
    paths = sorted({t for entry in models.values() for t in entry["textures"]})
    aliases = {path: "t" + str(i) for i, path in enumerate(paths)}
    controls = {}
    for half, index in (("lower", 0), ("upper", 1)):
        controls["controller.render.ed.model_" + half] = {
            "arrays": {"geometries": {"Array.shape": ["Geometry." + ("door_" + half if models[n]["kind"] == "door" else
                                                                       "chest" if index == 0 else "empty") for n in names]},
                       "textures": {"Array.skin": ["Texture." + aliases[models[n]["textures"][index]] for n in names]}},
            "geometry": "Array.shape[query.variant]", "materials": [{"*": "Material.default"}],
            "textures": ["Array.skin[query.variant]"]}
    write("resource_pack/render_controllers/model.render_controllers.json", {"format_version": "1.8.0", "render_controllers": controls})
    write("resource_pack/entity/model.entity.json", {"format_version": "1.10.0", "minecraft:client_entity": {"description": {
        "identifier": "ed:model", "materials": {"default": "entity_alphatest"},
        "textures": {aliases[p]: p for p in paths},
        "geometry": {g["description"]["identifier"].split(".")[-1]: g["description"]["identifier"] for g in geometries},
        "animations": {"transform": "animation.ed.cuboid_transform"}, "scripts": {"animate": ["transform"]},
        "render_controllers": list(controls)}}})
    print(f"Built {len(models)} chest/door display mappings with four shared geometries.")


if __name__ == "__main__":
    main()
