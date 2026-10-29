"""Native API and pack-reference checks without launching the server."""
import ast
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from endstone.level import Dimension
from endstone.actor import Actor
from endstone import Player, Server
from endstone.block import BlockData
from endstone.event import Event
from endstone.plugin.plugin_loader import _build_commands, _build_permissions
from endstone_entity_displays import EntityDisplaysPlugin
from endstone_entity_displays.packs import bundled_files
from endstone_entity_displays.catalog import PROPERTIES, load_catalog, load_models

commands = _build_commands(EntityDisplaysPlugin.commands)
permissions = _build_permissions({key: dict(value) for key, value in EntityDisplaysPlugin.permissions.items()})
assert commands[0].name == "ed" and commands[0].aliases == ["entitydisplay"]
assert len(permissions) == 1 and hasattr(Dimension, "spawn_actor") and hasattr(Actor, "remove")
assert hasattr(Server, "create_block_data") and hasattr(BlockData, "runtime_id") and hasattr(Player, "send_packet")
handlers = [method for _, method in inspect.getmembers(EntityDisplaysPlugin, inspect.isfunction)
            if getattr(method, "_is_event_handler", False)]
assert len(handlers) == 4
for handler in handlers:
    signature = inspect.signature(handler)
    assert list(signature.parameters) == ["self", "event"]
    event_type = signature.parameters["event"].annotation
    assert isinstance(event_type, type) and issubclass(event_type, Event), signature
for node in ast.walk(ast.parse(inspect.getsource(EntityDisplaysPlugin))):
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name) and node.value.id == "self":
        descriptor = inspect.getattr_static(EntityDisplaysPlugin, node.attr, None)
        assert not isinstance(descriptor, property) or descriptor.fset is not None
files = bundled_files()
entity = json.loads(files["resource_pack/entity/oak_planks.entity.json"])["minecraft:client_entity"]["description"]
geometry = json.loads(files["resource_pack/models/entity/oak_planks.geo.json"])["minecraft:geometry"][0]["description"]
controllers = json.loads(files["resource_pack/render_controllers/oak_planks.render_controllers.json"])["render_controllers"]
assert entity["geometry"]["default"] == geometry["identifier"]
assert entity["render_controllers"][0] in controllers
assert entity["textures"]["default"] == "textures/blocks/planks_oak"
assert entity["identifier"] == json.loads(files["behavior_pack/entities/oak_planks.json"])["minecraft:entity"]["description"]["identifier"]
cuboid = json.loads(files["behavior_pack/entities/cuboid.json"])["minecraft:entity"]
definitions = cuboid["description"]["properties"]
assert list(definitions) == list(PROPERTIES) and len(definitions) == 6
for name, definition in definitions.items():
    assert definition["type"] == "int" and definition["client_sync"]
    assert definition["range"] == PROPERTIES[name]["range"] and definition["default"] == PROPERTIES[name]["default"]
client = json.loads(files["resource_pack/entity/cuboid.entity.json"])["minecraft:client_entity"]["description"]
assert client["identifier"] == cuboid["description"]["identifier"] == "ed:cuboid"
catalog = load_catalog()
assert "minecraft:stone" in catalog and "minecraft:oak_planks" in catalog
geometries = json.loads(files["resource_pack/models/entity/cuboid.geo.json"])["minecraft:geometry"]
assert set(client["geometry"].values()) == {g["description"]["identifier"] for g in geometries}
controls = json.loads(files["resource_pack/render_controllers/cuboid.render_controllers.json"])["render_controllers"]
assert set(client["render_controllers"]) == set(controls)
for controller in controls.values():
    textures = controller["arrays"]["textures"]["Array.face"]
    materials = controller["arrays"]["materials"]["Array.surface"]
    assert len(textures) == len(materials) == len(catalog)
    assert all(texture.split(".", 1)[1] in client["textures"] for texture in textures)
animation = json.loads(files["resource_pack/animations/cuboid.animation.json"])["animations"]["animation.ed.cuboid_transform"]
assert set(animation["bones"]) == {"yaw", "pitch", "roll", "box"}
models = load_models()
bp_model = json.loads(files["behavior_pack/entities/model.json"])["minecraft:entity"]
assert bp_model["description"]["properties"] == definitions
client_model = json.loads(files["resource_pack/entity/model.entity.json"])["minecraft:client_entity"]["description"]
assert bp_model["description"]["identifier"] == client_model["identifier"] == "ed:model"
shapes = json.loads(files["resource_pack/models/entity/model.geo.json"])["minecraft:geometry"]
assert set(client_model["geometry"].values()) == {g["description"]["identifier"] for g in shapes}
controls = json.loads(files["resource_pack/render_controllers/model.render_controllers.json"])["render_controllers"]
assert set(client_model["render_controllers"]) == set(controls)
for controller in controls.values():
    for key, prefix, aliases in (("geometries", "Array.shape", client_model["geometry"]), ("textures", "Array.skin", client_model["textures"])):
        entries = controller["arrays"][key][prefix]
        assert len(entries) == len(models)
        assert all(entry.split(".", 1)[1] in aliases for entry in entries)
assert client_model["animations"]["transform"] == "animation.ed.cuboid_transform"
print(f"Native commands, 4 event signatures, packet APIs, all {len(files)} pack files, {len(catalog)} cuboid and {len(models)} special model mappings validated.")
