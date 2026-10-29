import enum
import importlib
import io
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class Player:
    def __init__(self, dimension, allowed=True):
        self.dimension, self.allowed = dimension, allowed
        self.location = Location(dimension, .5, 64, .5)
        self.is_sneaking = False
        self.unique_id, self.is_dead = "test-player", False
        self.messages, self.errors, self.packets = [], [], []

    def has_permission(self, name):
        return self.allowed

    def send_message(self, value):
        self.messages.append(value)

    def send_error_message(self, value):
        self.errors.append(value)

    def send_packet(self, packet_id, payload):
        self.packets.append((packet_id, payload))


class Location:
    def __init__(self, dimension, x, y, z, pitch=0, yaw=0):
        self.dimension, self.x, self.y, self.z = dimension, x, y, z
        self.pitch, self.yaw = pitch, yaw


class Actor:
    def __init__(self, location, kind="ed:oak_planks"):
        self.location, self.type = location, kind
        self.is_valid, self.is_dead, self.removed = True, False, False

    def remove(self):
        self.removed, self.is_valid = True, False


class Dimension:
    def __init__(self):
        self.type = types.SimpleNamespace(value=0)
        self.blocks, self.actors, self.spawns = {}, [], []

    def get_block_at(self, x, y, z):
        return types.SimpleNamespace(type=self.blocks.get((x, y, z), "minecraft:air"))

    def spawn_actor(self, location, kind):
        actor = Actor(location, kind)
        self.actors.append(actor)
        self.spawns.append(actor)
        return actor


modules = {name: types.ModuleType(name) for name in ("endstone", "endstone.level", "endstone.plugin", "endstone.event")}
modules["endstone"].Player = Player
modules["endstone.level"].Location = Location
modules["endstone.plugin"].Plugin = type("Plugin", (), {"register_events": lambda *args: None})
modules["endstone.event"].event_handler = lambda function: function
for event_name in ("PlayerJoinEvent", "PlayerQuitEvent", "PlayerRespawnEvent", "PlayerDimensionChangeEvent"):
    setattr(modules["endstone.event"], event_name, type(event_name, (), {}))
with patch.dict(sys.modules, modules):
    plugin_code = importlib.import_module("endstone_entity_displays.plugin")
    placement = importlib.import_module("endstone_entity_displays.placement")
    packs = importlib.import_module("endstone_entity_displays.packs")
    storage = importlib.import_module("endstone_entity_displays.store")
    rendering = importlib.import_module("endstone_entity_displays.renderer")
    packets = importlib.import_module("endstone_entity_displays.packets")
    transforms = importlib.import_module("endstone_entity_displays.transforms")
    spider_code = importlib.import_module("endstone_entity_displays.spider")


class Server:
    def __init__(self, players=()):
        self.protocol_version, self.online_players = 2193, list(players)
        self.reads, self.tasks = [], []
        self.scheduler = types.SimpleNamespace(run_task=self.run_task)

    def run_task(self, plugin, callback, delay, period):
        task = types.SimpleNamespace(callback=callback, delay=delay, period=period, cancelled=False)
        task.cancel = lambda: setattr(task, "cancelled", True)
        self.tasks.append(task)
        return task

    def create_block_data(self, name):
        self.reads.append(name)
        values = {"minecraft:oak_planks": 5, "minecraft:stone": 123456, "minecraft:glass": 134,
                  "minecraft:oak_stairs": 99, "minecraft:oak_slab": 101, "minecraft:oak_log": 227,
                  "minecraft:black_concrete": 251, "minecraft:gray_concrete": 252, "minecraft:red_concrete": 253,
                  "minecraft:chest": 254, "minecraft:trapped_chest": 255, "minecraft:ender_chest": 256,
                  "minecraft:wooden_door": 257, "minecraft:iron_door": 258, "minecraft:spruce_door": 259,
                  "minecraft:copper_chest": 260, "minecraft:waxed_oxidized_copper_door": 261,
                  "minecraft:air": 0, "custom:marble": 0xf1234567}
        if name not in values:
            raise ValueError("Unknown block")
        return types.SimpleNamespace(type=name, runtime_id=values[name])


class PlacementTests(unittest.TestCase):
    def test_free_floating_cube_is_three_blocks_ahead(self):
        point = placement.spawn_position((.5, 65.62, .5), (0, 0, 1), lambda *cell: "minecraft:air")
        self.assertEqual(point, (.5, 65.12, 3.5))

    def test_floor_placement_is_above_surface(self):
        point = placement.spawn_position((.5, 65.62, .5), (0, -1, 0),
                                         lambda x, y, z: "minecraft:stone" if y < 64 else "minecraft:air")
        self.assertEqual(point, (.5, 64., .5))

    def test_wall_placement_is_adjacent(self):
        point = placement.spawn_position((.5, 65.62, .5), (0, 0, 1),
                                         lambda x, y, z: "minecraft:stone" if z == 4 else "minecraft:air")
        self.assertEqual(point, (.5, 65., 3.5))

    def test_negative_coordinates_use_floor_not_truncation(self):
        cells = list(placement.voxels((-.5, -59.5, -.5), (0, -1, 0), 2))
        self.assertEqual(cells[0], ((-1, -60, -1), 0))
        self.assertEqual(cells[1], ((-1, -61, -1), .5))

    def test_diagonal_and_axis_rays_are_finite(self):
        for vector in ((1, 1, 1), (1, 0, 0), (0, 0, -1), (0, -1, 0)):
            cells = list(placement.voxels((0, 0, 0), vector))
            self.assertLess(len(cells), 40)
            self.assertTrue(all(distance <= 6 for _, distance in cells))
        with self.assertRaises(ValueError):
            list(placement.voxels((0, 0, 0), (0, 0, 0)))
        with self.assertRaises(ValueError):
            list(placement.voxels((math.nan, 0, 0), (1, 0, 0)))

    def test_body_clearance_checks_neighbouring_cells(self):
        with self.assertRaises(ValueError):
            placement.spawn_position((0, 65.62, .5), (0, 0, 1),
                                     lambda x, y, z: "minecraft:stone" if x == -1 and z == 3 else "minecraft:air")

    def test_eye_inside_solid_block_is_rejected(self):
        with self.assertRaises(ValueError):
            placement.spawn_position((.5, 65.62, .5), (0, 0, 1), lambda *cell: "minecraft:stone")

    def test_visual_cube_ray_hit_and_miss(self):
        self.assertEqual(placement.cube_distance((.5, 65.62, .5), (0, 0, 1), (.5, 65.12, 3.5)), 2.5)
        self.assertIsNone(placement.cube_distance((.5, 65.62, .5), (0, 0, -1), (.5, 65.12, 3.5)))
        self.assertIsNone(placement.cube_distance((.5, 65.62, .5), (0, 0, 1), (5, 65.12, 3.5)))
        self.assertIsNone(placement.cube_distance((.5, 65.62, .5), (0, 0, 1), (.5, 65.12, 10)))

    def test_direction_and_crouch_height(self):
        location = Location(None, 0, 64, 0, 0, 90)
        origin, direction = placement.view_ray(location, True)
        self.assertAlmostEqual(origin[1], 65.27)
        self.assertAlmostEqual(direction[0], -1)


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.plugin = plugin_code.EntityDisplaysPlugin()
        self.logs = []
        self.plugin.logger = types.SimpleNamespace(info=self.logs.append, error=self.logs.append, warning=self.logs.append)
        self.dimension = Dimension()
        self.player = Player(self.dimension)
        self.server = self.plugin.server = Server([self.player])
        self.temporary = tempfile.TemporaryDirectory(prefix="display-plugin-", dir=ROOT / "tests")
        self.addCleanup(self.temporary.cleanup)
        self.plugin.data_folder = Path(self.temporary.name)
        self.plugin.on_enable()
        self.command = types.SimpleNamespace(name="ed")

    def run_command(self, *args, sender=None):
        return self.plugin.on_command(sender or self.player, self.command, list(args))

    def test_create_is_native_block_visual_not_world_actor_or_setblock(self):
        self.run_command("create")
        self.assertFalse(self.dimension.spawns)
        self.assertEqual(len(self.plugin.store.displays), 1)
        self.assertEqual(next(iter(self.plugin.store.displays.values())).block, "minecraft:oak_planks")
        self.assertEqual(self.player.packets[0][0], packets.ADD_ACTOR)
        self.assertFalse(self.dimension.blocks)

    def test_no_args_and_alias(self):
        self.command.name = "entitydisplay"
        self.run_command()
        self.assertEqual(len(self.plugin.store.displays), 1)

    def test_remove_looks_at_visual_cube_not_tiny_collision(self):
        self.run_command("create")
        self.run_command("remove")
        self.assertFalse(self.plugin.store.displays)
        self.assertEqual(self.player.packets[-1][0], packets.REMOVE_ACTOR)

    def test_all_registered_ids_not_just_oak(self):
        for name in ("minecraft:stone", "minecraft:glass", "minecraft:oak_stairs", "minecraft:oak_slab", "custom:marble"):
            self.run_command("create", name)
        self.assertEqual(len(self.plugin.store.displays), 5)
        self.assertFalse(self.player.errors)
        self.assertFalse(self.dimension.spawns)
        self.assertEqual(len(self.server.reads), 5)

    def test_unknown_item_ids_and_invalid_identifiers_are_rejected_without_writes(self):
        for name in ("minecraft:diamond_sword", "minecraft:not_a_block", "stone", "Minecraft:Stone", "minecraft:stone;kill", "minecraft:air"):
            self.run_command("create", name)
        self.assertFalse(self.plugin.store.displays)
        self.assertFalse(self.player.packets)
        self.assertFalse((self.plugin.data_folder / "displays.json").exists())

    def test_block_id_resolution_is_cached(self):
        self.run_command("create", "minecraft:stone")
        self.run_command("create", "minecraft:stone")
        self.assertEqual(self.server.reads, ["minecraft:stone"])

    def test_remove_still_handles_legacy_oak_entity(self):
        actor = Actor(Location(self.dimension, .5, 65.12, 3.5))
        self.dimension.actors.append(actor)
        self.run_command("remove")
        self.assertTrue(actor.removed)

    def test_nearest_between_saved_display_and_legacy_entity(self):
        self.run_command("create", "minecraft:stone")
        old = Actor(Location(self.dimension, .5, 65.12, 2.5))
        self.dimension.actors.append(old)
        self.run_command("remove")
        self.assertTrue(old.removed)
        self.assertEqual(len(self.plugin.store.displays), 1)

    def test_remove_does_not_touch_other_entity_types(self):
        cow = Actor(Location(self.dimension, .5, 65.12, 3.5), "minecraft:cow")
        self.dimension.actors.append(cow)
        self.run_command("remove")
        self.assertFalse(cow.removed)
        self.assertTrue(self.player.errors)

    def test_remove_cannot_pick_through_wall(self):
        actor = Actor(Location(self.dimension, .5, 65.12, 5.5))
        self.dimension.actors.append(actor)
        self.dimension.blocks[(0, 65, 4)] = "minecraft:stone"
        self.run_command("remove")
        self.assertFalse(actor.removed)

    def test_only_nearest_aimed_display_is_removed(self):
        near, far = Actor(Location(self.dimension, .5, 65.12, 2.5)), Actor(Location(self.dimension, .5, 65.12, 4.5))
        self.dimension.actors.extend([far, near])
        self.run_command("remove")
        self.assertTrue(near.removed)
        self.assertFalse(far.removed)

    def test_disabled_and_permission_and_console(self):
        self.player.allowed = False
        self.run_command("create")
        self.assertFalse(self.dimension.spawns)
        self.player.allowed = True
        self.plugin.on_disable()
        self.run_command("create")
        self.assertFalse(self.dimension.spawns)
        sender = types.SimpleNamespace(send_error_message=self.player.errors.append)
        self.run_command("create", sender=sender)
        self.assertIn("in-game", self.player.errors[-1])

    def test_help_and_invalid_args_do_not_create(self):
        self.run_command("help")
        self.run_command("bad")
        self.run_command("create", "bad")
        self.run_command("remove", "minecraft:stone")
        self.run_command("help", "bad")
        self.run_command("create", "minecraft:stone", "bad")
        self.assertFalse(self.dimension.spawns)
        self.assertFalse(self.plugin.store.displays)

    def test_disable_saves_displays_and_removes_only_client_visuals(self):
        self.run_command("create")
        task = self.plugin.task
        self.plugin.on_disable()
        self.assertEqual(len(storage.Store(self.plugin.data_folder / "displays.json").displays), 1)
        self.assertEqual(self.player.packets[-1][0], packets.REMOVE_ACTOR)
        self.assertTrue(task.cancelled)

    def test_storage_failure_does_not_spawn_or_claim_success(self):
        with patch.object(self.plugin.store, "commit", side_effect=OSError("disk full")):
            self.run_command("create")
        self.assertTrue(self.player.errors)
        self.assertFalse(self.player.messages)
        self.assertFalse(self.player.packets)
        self.assertFalse(self.plugin.store.displays)

    def test_nothing_is_polled_until_first_display_and_last_removal_stops_polling(self):
        self.assertFalse(self.server.tasks)
        self.run_command("create", "minecraft:stone")
        task = self.plugin.task
        self.assertEqual((task.delay, task.period), (20, 20))
        self.run_command("remove")
        self.assertTrue(task.cancelled)
        self.assertIsNone(self.plugin.task)

    def test_remove_failure_preserves_visual_and_storage(self):
        self.run_command("create", "minecraft:stone")
        before = list(self.player.packets)
        with patch.object(self.plugin.store, "commit", side_effect=OSError("disk full")):
            self.run_command("remove")
        self.assertEqual(len(self.plugin.store.displays), 1)
        self.assertEqual(self.player.packets, before)

    def test_last_removal_packet_failure_keeps_polling_until_delivered(self):
        self.run_command("create", "minecraft:stone")
        task = self.plugin.task
        with patch.object(self.player, "send_packet", side_effect=RuntimeError("busy")):
            self.run_command("remove")
        self.assertFalse(self.plugin.store.displays)
        self.assertFalse(task.cancelled)
        task.callback()
        self.assertEqual(self.player.packets[-1][0], packets.REMOVE_ACTOR)
        self.assertTrue(task.cancelled)
        self.assertIsNone(self.plugin.task)

    def test_native_event_hooks_reset_and_forget_viewers(self):
        self.run_command("create", "minecraft:stone")
        event = types.SimpleNamespace(player=self.player)
        self.plugin.on_respawn(event)
        self.assertNotIn(self.player.unique_id, self.plugin.renderer.viewers)
        self.plugin.renderer.sync_player(self.player, immediate=True)
        self.plugin.on_dimension_change(event)
        self.assertNotIn(self.player.unique_id, self.plugin.renderer.viewers)
        self.plugin.renderer.sync_player(self.player, immediate=True)
        self.plugin.on_quit(event)
        self.assertNotIn(self.player.unique_id, self.plugin.renderer.viewers)
        self.plugin.on_join(event)

    def test_packet_error_keeps_saved_display_and_retries(self):
        with patch.object(self.player, "send_packet", side_effect=RuntimeError("disconnect")):
            self.run_command("create", "minecraft:stone")
        self.assertEqual(len(self.plugin.store.displays), 1)
        self.plugin.renderer.tick()
        self.assertEqual(self.player.packets[0][0], packets.ADD_ACTOR)

    def test_unsupported_protocol_fails_closed(self):
        self.server.protocol_version = 99999
        self.plugin.on_enable()
        self.run_command("create", "minecraft:stone")
        self.assertFalse(self.plugin.ready)
        self.assertFalse(self.player.packets)

    def test_startup_installs_from_current_server_root(self):
        with patch.object(plugin_code, "install_packs", return_value="unchanged") as install:
            self.plugin.on_load()
            install.assert_called_once()
            self.plugin.on_enable()
            self.assertTrue(self.plugin.ready)

    def test_legacy_pack_failure_does_not_disable_native_blocks(self):
        with patch.object(plugin_code, "install_packs", side_effect=ValueError("bad pack")):
            self.plugin.on_load()
            self.plugin.on_enable()
            self.run_command("create")
            self.assertEqual(len(self.plugin.store.displays), 1)


class APITests(unittest.TestCase):
    setUp = PluginTests.setUp
    run_command = PluginTests.run_command

    def test_create_get_and_read_only_snapshot(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2))
        self.assertEqual(self.plugin.api.get(handle.id[:8]).id, handle.id)
        self.assertEqual(handle.position, (2, 64, 2))
        self.assertEqual(handle.snapshot.mode, "native")
        with self.assertRaises(AttributeError):
            handle.snapshot.block = "minecraft:glass"

    def test_real_width_height_depth_not_hitbox_metadata(self):
        handle = self.plugin.api.create("minecraft:oak_planks", (2, 64, 2))
        handle.width = 2
        handle.height = 3
        handle.depth = .25
        self.assertEqual(handle.size, (2, 3, .25))
        self.assertEqual(handle.snapshot.mode, "cuboid")
        saved = storage.Store(self.plugin.data_folder / "displays.json").displays[handle.id]
        self.assertEqual(saved.size, (2, 3, .25))

    def test_move_and_relative_offset_keep_identity(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2))
        identity = handle.id
        handle.move_to(10, 70, 5).translate(-2, 1, 3)
        self.assertEqual(handle.position, (8, 71, 8))
        self.assertEqual(handle.id, identity)

    def test_movement_uses_update_packet_not_despawn_respawn(self):
        self.run_command("create", "minecraft:stone")
        handle = self.plugin.api.list()[0]
        before = len(self.player.packets)
        handle.move_to(.5, 65, 4)
        self.assertEqual([p[0] for p in self.player.packets[before:]], [packets.MOVE_ACTOR])
        self.plugin.poll()
        self.assertEqual(len(self.player.packets), before + 1)

    def test_switch_to_cuboid_once_then_live_properties_preserve_actor(self):
        self.run_command("create", "minecraft:stone")
        handle = self.plugin.api.list()[0]
        before = len(self.player.packets)
        handle.resize(2, 3, 1)
        self.assertEqual([p[0] for p in self.player.packets[before:]],
                         [packets.SYNC_ACTOR_PROPERTY, packets.REMOVE_ACTOR, packets.ADD_ACTOR])
        before = len(self.player.packets)
        runtime = self.plugin.renderer.payloads[handle.id][4]
        handle.resize(3, 4, .5)
        self.assertEqual([p[0] for p in self.player.packets[before:]], [packets.MOVE_ACTOR, packets.SET_ACTOR_DATA])
        self.assertEqual(self.plugin.renderer.payloads[handle.id][4], runtime)

    def test_rotation_normalized_and_cuboid_properties_update_once(self):
        handle = self.plugin.api.create("minecraft:stone", (.5, 64, 3.5), size=(2, 3, 1))
        self.plugin.renderer.sync_player(self.player, immediate=True)
        before = len(self.player.packets)
        handle.rotate(450, -540, 720)
        self.assertEqual(handle.snapshot.rotation, (90, -180, 0))
        self.assertEqual([p[0] for p in self.player.packets[before:]], [packets.SET_ACTOR_DATA])

    def test_clone_has_new_id_and_independent_state(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2), size=(2, 3, 1))
        other = handle.clone(position=(3, 64, 2))
        self.assertNotEqual(handle.id, other.id)
        self.assertEqual(other.size, handle.size)
        other.set_block("minecraft:glass")
        self.assertEqual(handle.snapshot.block, "minecraft:stone")
        self.assertEqual(other.snapshot.block, "minecraft:glass")

    def test_scale_factor_preserves_aspect_ratio(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2), size=(2, 3, .5))
        handle.scale(2)
        self.assertEqual(handle.size, (4, 6, 1))
        with self.assertRaises(ValueError):
            handle.scale(-1)

    def test_no_save_frame_does_not_revalidate_entire_store(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2))
        with patch.object(self.plugin.store, "validated", side_effect=AssertionError("No whole-store work")):
            handle.move_to(3, 64, 2, save=False)
        self.assertEqual(handle.position, (3, 64, 2))

    def test_partial_packet_failure_retries_latest_transform(self):
        self.run_command("create", "minecraft:stone")
        handle = self.plugin.api.list()[0]
        handle.resize(2, 3, 1)
        original = self.plugin.renderer.viewers[self.player.unique_id]["versions"][handle.id]
        with patch.object(self.player, "send_packet", side_effect=RuntimeError("busy")):
            handle.resize(4, 5, 1)
        self.assertEqual(self.plugin.renderer.viewers[self.player.unique_id]["versions"][handle.id], original)
        self.plugin.poll()
        self.assertEqual(self.plugin.renderer.viewers[self.player.unique_id]["versions"][handle.id], handle.snapshot)

    def test_cuboid_failure_does_not_poison_native_block_cache(self):
        self.plugin.renderer.catalog.pop("minecraft:stone", None)
        display = storage.validate_record({"id": "c" * 32, "block": "minecraft:stone", "dimension": 0,
                                           "position": [0, 64, 2], "mode": "cuboid"})
        self.plugin.store.put(display)
        self.assertIsNone(self.plugin.renderer.payload(display))
        self.assertIsNotNone(self.plugin.renderer.resolve("minecraft:stone"))

    def test_temporary_display_never_written_or_restored(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2), persistent=False)
        self.assertFalse((self.plugin.data_folder / "displays.json").exists())
        handle.resize(2, 3, 1)
        self.plugin.api.flush()
        self.assertFalse(storage.Store(self.plugin.data_folder / "displays.json").displays)
        handle.remove()
        self.assertFalse(self.plugin.api.list())

    def test_save_false_skips_per_frame_disk_writes_then_flush_saves(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2))
        path = self.plugin.data_folder / "displays.json"
        original = path.read_bytes()
        handle.move_to(3, 65, 3, save=False)
        handle.move_to(4, 66, 4, save=False)
        self.assertEqual(path.read_bytes(), original)
        self.plugin.api.flush()
        self.assertEqual(storage.Store(path).displays[handle.id].position, (4, 66, 4))

    def test_invalid_transforms_do_not_mutate_or_write(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2))
        original = handle.snapshot
        for changes in ({"size": (-1, 1, 1)}, {"size": (1, 33, 1)}, {"size": (1, math.nan, 1)},
                        {"position": (0, math.inf, 0)}, {"rotation": (math.nan, 0, 0)},
                        {"persistent": "yes"}, {"mode": []}, {"unknown": 5}):
            with self.assertRaises(ValueError):
                handle.update(**changes)
            self.assertEqual(handle.snapshot, original)

    def test_native_mode_cannot_claim_nonuniform_rendering(self):
        with self.assertRaises(ValueError):
            self.plugin.api.create("minecraft:stone", (2, 64, 2), size=(2, 3, 1), mode="native")
        self.assertFalse(self.plugin.api.list())

    def test_unknown_cuboid_texture_mapping_fails_before_changes(self):
        handle = self.plugin.api.create("custom:marble", (2, 64, 2))
        with self.assertRaises(ValueError):
            handle.resize(2, 3, 1)
        self.assertEqual(handle.snapshot.mode, "native")

    def test_disabled_or_wrong_thread_api_refuses_native_access(self):
        errors = []
        def worker():
            try:
                self.plugin.api.create("minecraft:stone", (2, 64, 2))
            except RuntimeError as error:
                errors.append(str(error))
        task = threading.Thread(target=worker)
        task.start()
        task.join(timeout=3)
        self.assertEqual(len(errors), 1)
        self.assertFalse(self.server.reads)
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2))
        self.plugin.on_disable()
        with self.assertRaises(RuntimeError):
            handle.move_to(3, 64, 2)

    def test_failed_disk_update_keeps_snapshot_and_viewers(self):
        self.run_command("create", "minecraft:stone")
        handle = self.plugin.api.list()[0]
        original, messages = handle.snapshot, list(self.player.packets)
        with patch.object(storage.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                handle.move_to(3, 64, 3)
        self.assertEqual(handle.snapshot, original)
        self.assertEqual(self.player.packets, messages)

    def test_stale_handles_and_prefix_ambiguity(self):
        handle = self.plugin.api.create("minecraft:stone", (2, 64, 2))
        handle.remove()
        self.assertIsNone(self.plugin.api.get(handle.id))
        with self.assertRaises(ValueError):
            handle.resize(2, 3, 1)
        for tail in ("0", "1"):
            display = storage.validate_record({"id": "a" * 8 + tail * 24, "block": "minecraft:stone", "dimension": 0, "position": [2, 64, 2]})
            self.plugin.store.put(display)
        with self.assertRaises(ValueError):
            self.plugin.api.get("a" * 8)

    def test_selected_commands_resize_move_rotate_clone_and_block(self):
        self.run_command("create", "minecraft:stone")
        self.run_command("size", "2", "3", "0.5")
        handle = self.plugin.api.list()[0]
        self.assertEqual(handle.size, (2, 3, .5))
        self.run_command("move", "5", "70", "5")
        self.run_command("offset", "1", "0", "-1")
        self.run_command("rotate", "0", "45", "0")
        self.run_command("block", "minecraft:glass")
        self.assertEqual(handle.position, (6, 70, 4))
        self.assertEqual(handle.snapshot.rotation, (0, 45, 0))
        self.assertEqual(handle.snapshot.block, "minecraft:glass")
        self.run_command("clone")
        self.assertEqual(len(self.plugin.api.list()), 2)
        self.assertFalse(self.player.errors)

    def test_remove_by_short_id_and_list_select(self):
        self.run_command("create", "minecraft:stone")
        handle = self.plugin.api.list()[0]
        self.run_command("list")
        self.run_command("select", handle.id[:8])
        self.run_command("info")
        self.run_command("remove", handle.id[:8])
        self.assertFalse(self.plugin.api.list())
        self.assertFalse(self.player.errors)

    def test_version_one_storage_loads_without_rewriting_and_migrates_on_save(self):
        path = self.plugin.data_folder / "old.json"
        path.write_text(json.dumps({"version": 1, "displays": [{"id": "a" * 32, "block": "minecraft:stone", "dimension": 0, "position": [0, 64, 0]}]}))
        original = path.read_bytes()
        old = storage.Store(path)
        self.assertEqual(path.read_bytes(), original)
        display = old.displays["a" * 32]
        self.assertEqual(display.size, (1, 1, 1))
        old.put(display)
        self.assertEqual(json.loads(path.read_bytes())["version"], 2)


class SpecialModelTests(unittest.TestCase):
    setUp = PluginTests.setUp
    run_command = PluginTests.run_command

    def test_doors_have_two_block_height_and_thin_depth_by_default(self):
        for name in ("minecraft:wooden_door", "minecraft:iron_door", "minecraft:spruce_door", "minecraft:waxed_oxidized_copper_door"):
            handle = self.plugin.api.create(name, (0, 64, 0))
            self.assertEqual(handle.snapshot.mode, "model")
            self.assertEqual(handle.size, (1, 2, .188))
        self.assertFalse(self.dimension.spawns)

    def test_chests_use_special_model_instead_of_falling_block(self):
        for name in ("minecraft:chest", "minecraft:trapped_chest", "minecraft:ender_chest", "minecraft:copper_chest"):
            handle = self.plugin.api.create(name, (0, 64, 0))
            self.assertEqual(handle.snapshot.mode, "model")
            self.assertEqual(handle.size, (.875, .875, .938))
            variant = self.plugin.renderer.models[name][0]
            self.assertEqual(self.plugin.renderer.variant(handle.snapshot), variant)

    def test_oak_door_alias_falls_back_to_registered_bedrock_name_and_caches(self):
        handle = self.plugin.api.create("minecraft:oak_door", (0, 64, 0))
        self.assertEqual(handle.snapshot.block, "minecraft:wooden_door")
        self.plugin.renderer.resolve("minecraft:oak_door")
        self.assertEqual(self.server.reads, ["minecraft:oak_door", "minecraft:wooden_door"])

    def test_registered_oak_name_is_not_forced_to_legacy_alias(self):
        with patch.object(self.server, "create_block_data", return_value=types.SimpleNamespace(type="minecraft:oak_door", runtime_id=600)):
            handle = self.plugin.api.create("minecraft:oak_door", (0, 64, 0))
        self.assertEqual(handle.snapshot.block, "minecraft:oak_door")
        self.assertEqual(handle.snapshot.mode, "model")

    def test_resize_rotate_move_and_clone_keep_special_shape(self):
        handle = self.plugin.api.create("minecraft:chest", (0, 64, 0), size=(2, 3, 4))
        self.plugin.renderer.sync_player(self.player, immediate=True)
        runtime = self.plugin.renderer.payloads[handle.id][4]
        before = len(self.player.packets)
        handle.resize(3, 4, 5).rotate(0, 45, 0).move_to(2, 65, 2)
        self.assertEqual(handle.snapshot.mode, "model")
        self.assertEqual(self.plugin.renderer.payloads[handle.id][4], runtime)
        self.assertNotIn(packets.ADD_ACTOR, [p[0] for p in self.player.packets[before:]])
        self.assertEqual(handle.clone().snapshot.mode, "model")

    def test_ordinary_block_changed_to_door_uses_natural_size(self):
        handle = self.plugin.api.create("minecraft:stone", (0, 64, 0))
        handle.set_block("minecraft:wooden_door")
        self.assertEqual(handle.size, (1, 2, .188))
        self.assertEqual(handle.snapshot.mode, "model")
        handle.set_block("minecraft:stone")
        self.assertEqual(handle.snapshot.mode, "cuboid")
        self.assertEqual(handle.size, (1, 2, .188))  # Preserve the edited bounding box.

    def test_explicit_cuboid_remains_an_intentionally_textured_box(self):
        handle = self.plugin.api.create("minecraft:chest", (0, 64, 0), mode="cuboid")
        self.assertEqual(handle.snapshot.mode, "cuboid")
        self.assertEqual(handle.size, (1, 1, 1))
        handle.update(mode="auto")
        self.assertEqual(handle.snapshot.mode, "model")

    def test_invalid_special_model_or_unavailable_pack_does_not_save(self):
        for name, mode in (("minecraft:stone", "model"), ("minecraft:chest", "native")):
            with self.assertRaises(ValueError):
                self.plugin.api.create(name, (0, 64, 0), mode=mode)
        self.plugin.renderer.cuboid_enabled = False
        with self.assertRaises(ValueError):
            self.plugin.api.create("minecraft:chest", (0, 64, 0))
        self.assertFalse(self.plugin.api.list())
        self.assertFalse((self.plugin.data_folder / "displays.json").exists())

    def test_model_and_cuboid_schemas_each_sent_once_and_before_spawn(self):
        self.plugin.api.create("minecraft:chest", (0, 64, 0))
        self.plugin.api.create("minecraft:wooden_door", (2, 64, 0))
        self.plugin.api.create("minecraft:stone", (4, 64, 0), mode="cuboid")
        self.plugin.renderer.sync_player(self.player, immediate=True)
        self.plugin.renderer.sync_player(self.player, immediate=True)
        ids = [p[0] for p in self.player.packets]
        self.assertEqual(ids.count(packets.SYNC_ACTOR_PROPERTY), 2)
        self.assertEqual(ids.count(packets.ADD_ACTOR), 3)
        self.assertEqual(ids[0], packets.SYNC_ACTOR_PROPERTY)
        self.assertEqual(self.plugin.renderer.viewers[self.player.unique_id]["schemas"], {"ed:model", "ed:cuboid"})

    def test_switching_between_box_and_model_recreates_once(self):
        self.run_command("create", "minecraft:chest")
        handle = self.plugin.api.list()[0]
        before = len(self.player.packets)
        handle.update(mode="cuboid")
        self.assertEqual([p[0] for p in self.player.packets[before:]],
                         [packets.SYNC_ACTOR_PROPERTY, packets.REMOVE_ACTOR, packets.ADD_ACTOR])
        before = len(self.player.packets)
        handle.update(mode="model")
        self.assertEqual([p[0] for p in self.player.packets[before:]], [packets.REMOVE_ACTOR, packets.ADD_ACTOR])

    def test_existing_saved_specials_upgrade_on_enable_without_file_rewrite(self):
        original = self.plugin.store.add("minecraft:wooden_door", 0, (0, 64, 0))
        path = self.plugin.data_folder / "displays.json"
        disk = path.read_bytes()
        self.plugin.on_disable()
        self.plugin.on_enable()
        record = self.plugin.store.displays[original.id]
        self.assertTrue(self.plugin.ready)
        self.assertEqual((record.mode, record.size, record.position), ("model", (1, 2, .188), original.position))
        self.assertEqual(path.read_bytes(), disk)
        self.plugin.api.flush()
        self.assertEqual(storage.Store(path).displays[original.id], record)

    def test_upgrade_that_would_exceed_ceiling_keeps_record_and_disk(self):
        original = self.plugin.store.add("minecraft:wooden_door", 0, (0, 319, 0))
        path = self.plugin.data_folder / "displays.json"
        disk = path.read_bytes()
        self.plugin.on_disable()
        self.plugin.on_enable()
        self.assertTrue(self.plugin.ready)
        self.assertEqual(self.plugin.store.displays[original.id], original)
        self.assertEqual(path.read_bytes(), disk)
        self.assertIsNone(self.plugin.renderer.payload(original))
        self.assertTrue(any("kept unchanged" in line for line in self.logs))

    def test_full_door_bounds_validated_before_write(self):
        with self.assertRaises(ValueError):
            self.plugin.api.create("minecraft:wooden_door", (0, 319, 0))
        self.assertFalse(self.plugin.api.list())
        handle = self.plugin.api.create("minecraft:wooden_door", (0, 318, 0))
        self.assertEqual(handle.size[1], 2)

    def test_command_rejects_ceiling_over_upper_half(self):
        self.dimension.blocks[(0, 67, 3)] = "minecraft:stone"
        self.run_command("create", "minecraft:wooden_door")
        self.assertFalse(self.plugin.api.list())
        self.assertTrue(any("clear space" in error for error in self.player.errors))

    def test_special_model_add_packet_complete_decode(self):
        handle = self.plugin.api.create("minecraft:wooden_door", (2, 64, 3))
        variant = self.plugin.renderer.variant(handle.snapshot)
        reader = PacketTests.Reader(packets.add_visual(-15, 15, handle.snapshot, variant))
        self.assertEqual((reader.sint(), reader.uint(), reader.string()), (-15, 15, "ed:model"))
        self.assertEqual(struct.unpack("<10f", reader.take(40)), (2, 65, 3, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(reader.uint(), 0)
        metadata = {}
        for _ in range(reader.uint()):
            key, kind = reader.uint(), reader.uint()
            self.assertEqual(reader.take(1)[0], kind)
            metadata[key] = reader.sint() if kind in (2, 7) else struct.unpack("<f", reader.take(4))[0]
        self.assertEqual(metadata[2], variant)
        self.assertEqual(metadata[38], 1)
        self.assertEqual(metadata[53], 0)
        self.assertEqual(metadata[54], 0)
        self.assertEqual(reader.uint(), 6)
        self.assertEqual([(reader.uint(), reader.sint()) for _ in range(6)], list(enumerate((1000, 2000, 188, 0, 0, 0))))
        self.assertEqual(reader.uint(), 0)
        self.assertEqual(reader.uint(), 0)
        self.assertEqual(reader.offset, len(reader.data))


class SpiderTests(unittest.TestCase):
    setUp = PluginTests.setUp
    run_command = PluginTests.run_command

    def test_layout_has_body_head_red_eyes_and_eight_two_part_legs(self):
        layout = spider_code.spider_layout((0, 64, 0))
        self.assertEqual(len(layout), 20)
        names = {p.name for p in layout}
        self.assertEqual(len(names), 20)
        self.assertEqual(len([p for p in layout if p.name.startswith("leg_") and p.name.endswith("_upper")]), 8)
        self.assertEqual(len([p for p in layout if p.name.startswith("leg_") and p.name.endswith("_lower")]), 8)
        self.assertEqual([p.block for p in layout if p.name.startswith("eye_")], ["minecraft:red_concrete"] * 2)
        self.assertTrue({"body", "head"} <= names)

    def test_layout_is_symmetric_and_legs_clear_floor(self):
        parts = {p.name: p for p in spider_code.spider_layout((0, 64, 0))}
        for i in range(4):
            for segment in ("upper", "lower"):
                a, b = parts[f"leg_left_{i}_{segment}"], parts[f"leg_right_{i}_{segment}"]
                self.assertAlmostEqual(a.position[0], -b.position[0])
                self.assertEqual(a.position[1:], b.position[1:])
                self.assertEqual(a.size, b.size)
                self.assertGreaterEqual(a.position[1], 64)

    def test_cardinal_rotation_changes_placement_and_bounding_size(self):
        a = {p.name: p for p in spider_code.spider_layout((0, 64, 0), 0)}
        b = {p.name: p for p in spider_code.spider_layout((0, 64, 0), 90)}
        self.assertAlmostEqual(b["head"].position[0], a["head"].position[2])
        self.assertEqual(b["head"].rotation, (0, 90, 0))
        for p in b.values():
            self.assertEqual(p.rotation[1] % 90, 0)
        for invalid in ((math.nan, 64, 0), (0, math.inf, 0)):
            with self.assertRaises(ValueError):
                spider_code.spider_layout(invalid)

    def test_all_parts_use_public_api_cuboids_without_disk_or_real_entities(self):
        demo = spider_code.create_spider(self.plugin.api, (0, 64, 0))
        self.assertEqual(len(self.plugin.store.displays), 20)
        self.assertFalse((self.plugin.data_folder / "displays.json").exists())
        self.assertTrue(all(not d.persistent and d.mode == "cuboid" for d in self.plugin.store.displays.values()))
        self.assertEqual(demo.body_id, demo.parts[0])
        self.assertFalse(self.dimension.spawns)
        self.assertFalse(self.dimension.blocks)

    def test_spawn_command_sends_whole_model_and_selects_body(self):
        self.run_command("spider")
        demo = self.plugin.spider_demos[self.player.unique_id]
        self.assertEqual(self.plugin.selected[self.player.unique_id], demo.body_id)
        self.assertEqual(sum(p[0] == packets.ADD_ACTOR for p in self.player.packets), 20)
        self.assertEqual(sum(p[0] == packets.SYNC_ACTOR_PROPERTY for p in self.player.packets), 1)
        self.assertEqual(len(self.server.tasks), 1)
        self.assertEqual(self.server.tasks[0].period, 20)
        self.assertFalse(self.player.errors)

    def test_repeat_replaces_only_own_previous_demo(self):
        permanent = self.plugin.api.create("minecraft:stone", (20, 64, 20))
        original_file = (self.plugin.data_folder / "displays.json").read_bytes()
        self.run_command("spider")
        previous = self.plugin.spider_demos[self.player.unique_id]
        self.run_command("spider")
        current = self.plugin.spider_demos[self.player.unique_id]
        self.assertTrue(set(previous.parts).isdisjoint(current.parts))
        self.assertTrue(all(identity not in self.plugin.store.displays for identity in previous.parts))
        self.assertEqual(len(self.plugin.store.displays), 21)
        self.assertIsNotNone(self.plugin.api.get(permanent.id))
        self.assertEqual((self.plugin.data_folder / "displays.json").read_bytes(), original_file)

    def test_remove_command_is_targeted_and_missing_parts_are_safe(self):
        self.run_command("spider")
        demo = self.plugin.spider_demos[self.player.unique_id]
        self.plugin.api.remove(demo.parts[3])
        self.plugin.api.get(demo.body_id).width = 2
        unrelated = self.plugin.api.create("minecraft:stone", (20, 64, 20))
        self.run_command("spider", "remove")
        self.assertEqual(set(self.plugin.store.displays), {unrelated.id})
        self.assertNotIn(self.player.unique_id, self.plugin.spider_demos)
        self.assertFalse(self.player.errors)

    def test_other_players_demo_is_not_removed(self):
        self.run_command("spider")
        second = Player(self.dimension)
        second.unique_id = "second-demo-owner"
        self.server.online_players.append(second)
        self.run_command("spider", sender=second)
        self.run_command("spider", "remove")
        self.assertEqual(len(self.plugin.store.displays), 20)
        self.assertIn(second.unique_id, self.plugin.spider_demos)

    def test_quit_cleans_own_demo_and_no_restart_records_exist(self):
        self.run_command("spider")
        self.plugin.on_quit(types.SimpleNamespace(player=self.player))
        self.assertFalse(self.plugin.store.displays)
        self.assertFalse(self.plugin.spider_demos)
        self.assertIsNone(self.plugin.task)
        self.assertFalse((self.plugin.data_folder / "displays.json").exists())

    def test_partial_creation_rolls_back_without_touching_existing_displays(self):
        permanent = self.plugin.api.create("minecraft:stone", (20, 64, 20))
        original = self.server.create_block_data
        def block(name):
            if name == "minecraft:red_concrete":
                raise ValueError("Missing eye block")
            return original(name)
        self.server.create_block_data = block
        with self.assertRaises(ValueError):
            spider_code.create_spider(self.plugin.api, (0, 64, 0))
        self.assertEqual(set(self.plugin.store.displays), {permanent.id})

    def test_failed_replacement_preserves_previous_demo(self):
        self.run_command("spider")
        previous = self.plugin.spider_demos[self.player.unique_id]
        self.player.location.y = 319.9
        self.run_command("spider")
        self.assertEqual(self.plugin.spider_demos[self.player.unique_id], previous)
        self.assertEqual(set(self.plugin.store.displays), set(previous.parts))
        self.assertTrue(self.player.errors)

    def test_bad_arguments_and_no_demo_remove_have_no_side_effects(self):
        self.run_command("spider", "bad")
        self.run_command("spider", "remove", "bad")
        self.run_command("spider", "remove")
        self.assertFalse(self.plugin.store.displays)
        self.assertFalse(self.player.packets)
        self.assertEqual(len(self.player.errors), 3)


class TransformTests(unittest.TestCase):
    def test_inverse_rotation_round_trip(self):
        point, rotation = (1, 2, 3), (23, -76, 19)
        rotated = transforms.transform(point, rotation)
        restored = transforms.transform(rotated, rotation, inverse=True)
        for a, b in zip(point, restored):
            self.assertAlmostEqual(a, b)

    def test_ray_hits_expanded_width_not_old_unit_cube(self):
        self.assertIsNotNone(transforms.ray_distance((1.5, 65.5, 0), (0, 0, 1), (0, 64, 3), (4, 3, 1)))
        self.assertIsNone(transforms.ray_distance((1.5, 65.5, 0), (0, 0, 1), (0, 64, 3)))

    def test_yaw_swaps_width_and_depth_and_picking_matches(self):
        extent = transforms.half_extents((4, 2, 1), (0, 90, 0))
        for a, b in zip(extent, (.5, 1, 2)):
            self.assertAlmostEqual(a, b)
        self.assertIsNone(transforms.ray_distance((1.5, 65, 0), (0, 0, 1), (0, 64, 3), (4, 2, 1), (0, 90, 0)))

    def test_size_precision_and_rotation_normalization(self):
        self.assertEqual(transforms.size_vector((1.2341, 2, .05)), (1.234, 2, .05))
        self.assertEqual(transforms.rotation_vector((360, 450, -450)), (0, 90, -90))


class PacketTests(unittest.TestCase):
    class Reader:
        def __init__(self, data):
            self.data, self.offset = data, 0

        def take(self, count):
            result = self.data[self.offset:self.offset + count]
            if len(result) != count:
                raise AssertionError("Truncated packet")
            self.offset += count
            return result

        def uint(self):
            result = 0
            for shift in range(0, 70, 7):
                byte = self.take(1)[0]
                result |= (byte & 127) << shift
                if not byte & 128:
                    return result
            raise AssertionError("Overlong varint")

        def sint(self):
            value = self.uint()
            return (value >> 1) ^ -(value & 1)

        def string(self):
            return self.take(self.uint()).decode("utf-8")

    def test_add_actor_complete_independent_wire_decode(self):
        unique, runtime = -(1 << 54) - 17, (1 << 54) + 17
        data = packets.add_block(unique, runtime, (1.5, -60, 2.5), 0xf1234567)
        reader = self.Reader(data)
        self.assertEqual(reader.sint(), unique)
        self.assertEqual(reader.uint(), runtime)
        self.assertEqual(reader.string(), "minecraft:falling_block")
        self.assertEqual(struct.unpack("<10f", reader.take(40)), (1.5, -59.5, 2.5, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(reader.uint(), 0)  # Attributes
        self.assertEqual(reader.uint(), 5)  # Metadata entries
        metadata = {}
        for _ in range(5):
            key, variant_type = reader.uint(), reader.uint()
            payload_type = reader.take(1)[0]
            self.assertEqual(payload_type, variant_type)  # Required since 2168.
            if payload_type in (2, 7):
                value = reader.sint()
            elif payload_type == 3:
                value = struct.unpack("<f", reader.take(4))[0]
            else:
                self.fail("Unexpected metadata payload")
            metadata[key] = value
        self.assertEqual(metadata[2], -249346713)
        self.assertEqual(metadata[38], 1.0)
        self.assertEqual(metadata[53], 0.0)
        self.assertEqual(metadata[54], 0.0)
        self.assertEqual(metadata[0] & ((1 << 48) | (1 << 49) | (1 << 5)), 0)
        self.assertEqual(metadata[0] & (1 << 16), 1 << 16)
        self.assertEqual(reader.uint(), 0)  # Int properties
        self.assertEqual(reader.uint(), 0)  # Float properties
        self.assertEqual(reader.uint(), 0)  # Links; no newer-version trailer.
        self.assertEqual(reader.offset, len(data))

    def test_remove_uses_signed_unique_not_unsigned_runtime(self):
        reader = self.Reader(packets.remove_block(-12345678901234))
        self.assertEqual(reader.sint(), -12345678901234)
        self.assertEqual(reader.offset, len(reader.data))

    def test_move_packet_independent_decode_and_scaled_center(self):
        display = storage.validate_record({"id": "a" * 32, "block": "minecraft:stone", "dimension": 0,
                                           "position": [2, 64, 3], "mode": "cuboid", "size": [2, 4, 1]})
        reader = self.Reader(packets.move_visual(3456, display))
        self.assertEqual(reader.uint(), 3456)
        self.assertEqual(reader.take(1), b"\x02")
        self.assertEqual(struct.unpack("<3f", reader.take(12)), (2, 66, 3))
        self.assertEqual(reader.take(3), b"\x00\x00\x00")
        self.assertEqual(reader.offset, len(reader.data))

    def test_property_update_independent_decode_uses_six_visual_properties(self):
        display = storage.validate_record({"id": "a" * 32, "block": "minecraft:stone", "dimension": 0,
                                           "position": [2, 64, 3], "mode": "cuboid", "size": [2, 4, .25],
                                           "rotation": [10, 20, -30]})
        reader = self.Reader(packets.update_visual(3456, display, 15))
        self.assertEqual(reader.uint(), 3456)
        count = reader.uint()
        metadata = {}
        for _ in range(count):
            key, kind = reader.uint(), reader.uint()
            self.assertEqual(reader.take(1)[0], kind)
            metadata[key] = reader.sint() if kind in (2, 7) else struct.unpack("<f", reader.take(4))[0]
        self.assertEqual(metadata[2], 15)
        self.assertEqual(metadata[53], 0)
        self.assertEqual(metadata[54], 0)
        self.assertEqual(reader.uint(), 6)
        actual = [(reader.uint(), reader.sint()) for _ in range(6)]
        self.assertEqual(actual, list(enumerate((2000, 4000, 250, 10000, 20000, -30000))))
        self.assertEqual(reader.uint(), 0)  # Float properties
        self.assertEqual(reader.uint(), 0)  # Input tick
        self.assertEqual(reader.offset, len(reader.data))

    def test_cuboid_schema_independent_network_nbt_decode(self):
        for kind in ("ed:cuboid", "ed:model"):
            with self.subTest(kind=kind):
                self.assert_schema(kind)

    def assert_schema(self, kind):
        from endstone_entity_displays.catalog import PROPERTIES
        reader = self.Reader(packets.schema(kind, PROPERTIES))
        self.assertEqual(reader.take(1), b"\x0a")
        self.assertEqual(reader.string(), "")
        self.assertEqual(reader.take(1), b"\x08")
        self.assertEqual(reader.string(), "type")
        self.assertEqual(reader.string(), kind)
        self.assertEqual(reader.take(1), b"\x09")
        self.assertEqual(reader.string(), "properties")
        self.assertEqual(reader.take(1), b"\x0a")
        self.assertEqual(reader.sint(), 6)
        for name, definition in PROPERTIES.items():
            self.assertEqual(reader.take(1), b"\x08")
            self.assertEqual(reader.string(), "name")
            self.assertEqual(reader.string(), name)
            for label, value in (("type", 0), ("min", definition["range"][0]), ("max", definition["range"][1])):
                self.assertEqual(reader.take(1), b"\x03")
                self.assertEqual(reader.string(), label)
                self.assertEqual(reader.sint(), value)
            self.assertEqual(reader.take(1), b"\x00")
        self.assertEqual(reader.take(1), b"\x00")
        self.assertEqual(reader.offset, len(reader.data))

    def test_integer_golden_bytes_and_bounds(self):
        self.assertEqual(packets.uint(300), b"\xac\x02")
        self.assertEqual(packets.sint(-1), b"\x01")
        self.assertEqual(packets.sint(1), b"\x02")
        for value in (-1, 1 << 64, True, 1.5):
            with self.assertRaises(ValueError):
                packets.uint(value)
        for value in (-(1 << 31) - 1, 1 << 31, False):
            with self.assertRaises(ValueError):
                packets.sint(value)

    def test_signed_and_unsigned_block_ids_preserve_all_32_bits(self):
        for value, expected in ((0, 0), (0x7fffffff, 0x7fffffff), (0x80000000, -(1 << 31)),
                                (0xffffffff, -1), (-1, -1)):
            self.assertEqual(packets.block_variant(value), expected)
        for value in (1 << 32, -(1 << 31) - 1, True, "12"):
            with self.assertRaises(ValueError):
                packets.block_variant(value)

    def test_bad_positions_do_not_encode(self):
        for position in ((0, math.nan, 0), (0, math.inf, 0), (0, 0)):
            with self.assertRaises(ValueError):
                packets.add_block(-5, 5, position, 123)


class StoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="display-store-", dir=ROOT / "tests")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "displays.json"
        self.store = storage.Store(self.path)

    def test_empty_store_does_not_create_a_file(self):
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.displays, {})

    def test_round_trip_names_and_positions_without_saved_runtime_ids(self):
        display = self.store.add("minecraft:stone", 0, (-1.5, -60, -10.25))
        record = json.loads(self.path.read_bytes())["displays"][0]
        self.assertEqual(set(record), {"id", "block", "dimension", "position", "size", "rotation", "mode", "persistent"})
        reloaded = storage.Store(self.path)
        self.assertEqual(reloaded.displays, {display.id: display})
        self.store.remove(display.id)
        self.assertFalse(storage.Store(self.path).displays)

    def test_failed_replace_preserves_memory_disk_and_cleans_own_temp(self):
        self.store.add("minecraft:stone", 0, (0, 64, 0))
        original, memory = self.path.read_bytes(), dict(self.store.displays)
        with patch.object(storage.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.add("minecraft:glass", 0, (1, 64, 1))
        self.assertEqual(self.store.displays, memory)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob(".ed-save-*")), [])

    def test_corrupt_json_and_unknown_storage_version_are_preserved(self):
        for content in (b"bad json", b'{"version":99,"displays":[]}', b'{"version":true,"displays":[]}',
                        b'{"version":1,"version":1,"displays":[]}', b'{"version":1,"displays":{}}'):
            self.path.write_bytes(content)
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                storage.Store(self.path)
            self.assertEqual(self.path.read_bytes(), content)

    def test_duplicate_ids_and_invalid_records_rejected(self):
        display = self.store.add("minecraft:stone", 0, (0, 64, 0)).encode()
        for records in ([display, display], [{**display, "position": [math.nan, 64, 0]}],
                        [{**display, "dimension": True}], [{**display, "block": "stone"}],
                        [{**display, "position": [0, 400, 0]}], [{**display, "extra": 1}]):
            with self.assertRaises(ValueError):
                storage.Store.validated(records)

    def test_dimension_height_and_world_border_validation(self):
        valid = {"id": "a" * 32, "block": "custom:marble", "dimension": 0, "position": [0, -64, 0]}
        self.assertEqual(storage.validate_record(valid).position, (0, -64, 0))
        for dimension, point in ((1, [0, 128, 0]), (2, [0, 256, 0]), (0, [30000000, 64, 0]),
                                 (0, [True, 64, 0]), (3, [0, 64, 0])):
            with self.assertRaises(ValueError):
                storage.validate_record({**valid, "dimension": dimension, "position": point})

    def test_cap_is_checked_before_commit(self):
        with patch.object(storage, "MAX_DISPLAYS", 1):
            self.store.add("minecraft:stone", 0, (0, 64, 0))
            original = self.path.read_bytes()
            with self.assertRaises(ValueError):
                self.store.add("minecraft:stone", 0, (1, 64, 0))
            self.assertEqual(self.path.read_bytes(), original)

    def test_linked_storage_refused(self):
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda p: p.name == self.path.parent.name or original(p)):
            with self.assertRaises(ValueError):
                storage.Store(self.path)


class RendererTests(unittest.TestCase):
    def test_2225_renderer_uses_new_spawn_trailer(self):
        self.server.protocol_version = 2225
        self.renderer = rendering.Renderer(self.server, self.store, self.logger)
        display = self.add()
        self.show()
        data = self.renderer.payload(display)
        expected = packets.add_visual(data[3], data[4], display, 123456, protocol=2193)
        self.assertEqual(self.player.packets, [(13, expected + b"\x00")])
        self.assertEqual(packets.add_block(-1, 1, (0, 64, 0), 5, 2225),
                         packets.add_block(-1, 1, (0, 64, 0), 5, 2193) + b"\x00")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="display-renderer-", dir=ROOT / "tests")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "displays.json"
        self.store = storage.Store(self.path)
        self.player = Player(Dimension())
        self.server = Server([self.player])
        self.logs = []
        self.logger = types.SimpleNamespace(error=self.logs.append, warning=self.logs.append)
        self.renderer = rendering.Renderer(self.server, self.store, self.logger)

    def add(self, block="minecraft:stone", dimension=0, position=(.5, 64, 3.5)):
        return self.store.add(block, dimension, position)

    def show(self):
        self.renderer.tick()
        self.renderer.tick()

    def test_initial_join_wait_then_stationary_visual_sends_only_once(self):
        self.add()
        self.renderer.tick()
        self.assertFalse(self.player.packets)
        self.renderer.tick()
        self.assertEqual(len(self.player.packets), 1)
        for _ in range(10):
            self.renderer.tick()
        self.assertEqual(len(self.player.packets), 1)
        self.assertEqual(self.server.reads, ["minecraft:stone"])

    def test_renderer_does_not_touch_world_actor_or_block_apis(self):
        self.add()
        self.player.dimension.get_block_at = lambda *args: self.fail("No world queries from renderer")
        self.player.dimension.actors = None
        self.show()
        self.assertEqual(len(self.player.packets), 1)

    def test_nearby_only_matching_dimension_and_spatial_bucket(self):
        self.add()
        self.add(dimension=1)
        self.add(position=(10000, 64, 10000))
        self.show()
        self.assertEqual(len(self.player.packets), 1)

    def test_hysteresis_hides_far_and_reenters_with_same_cached_payload(self):
        self.add()
        self.show()
        original = self.player.packets[0]
        self.player.location.x = 52
        self.renderer.tick()
        self.assertEqual(len(self.player.packets), 1)
        self.player.location.x = 60
        self.renderer.tick()
        self.assertEqual(self.player.packets[-1][0], packets.REMOVE_ACTOR)
        self.player.location.x = .5
        self.renderer.tick()
        self.assertEqual(self.player.packets[-1], original)

    def test_reset_and_dimension_change_do_not_leave_ghost_entities(self):
        self.add()
        self.add(dimension=1)
        self.show()
        self.player.dimension.type.value = 1
        self.renderer.tick()
        self.assertEqual(self.player.packets[-1][0], packets.REMOVE_ACTOR)
        self.renderer.tick()
        self.assertEqual(self.player.packets[-1][0], packets.ADD_ACTOR)
        self.assertEqual(len(self.player.packets), 3)

    def test_death_cleans_then_respawn_shows_again(self):
        self.add()
        self.show()
        self.player.is_dead = True
        self.renderer.tick()
        self.assertEqual(self.player.packets[-1][0], packets.REMOVE_ACTOR)
        self.player.is_dead = False
        self.show()
        self.assertEqual(self.player.packets[-1][0], packets.ADD_ACTOR)

    def test_quit_forgets_native_player_and_reconnect_recreates_visual(self):
        self.add()
        self.show()
        self.server.online_players.clear()
        self.renderer.tick()
        self.assertFalse(self.renderer.viewers)
        self.server.online_players.append(self.player)
        self.show()
        self.assertEqual(len(self.player.packets), 2)
        self.assertEqual(self.player.packets[0], self.player.packets[1])

    def test_removal_reaches_every_viewer_and_store_is_authoritative(self):
        second = Player(self.player.dimension)
        second.unique_id = "second-player"
        self.server.online_players.append(second)
        display = self.add()
        self.show()
        self.store.remove(display.id)
        self.renderer.removed(display.id)
        for player in (self.player, second):
            self.assertEqual(player.packets[-1][0], packets.REMOVE_ACTOR)
        self.assertFalse(self.renderer.payloads)

    def test_failed_removal_delivery_retried(self):
        display = self.add()
        self.show()
        self.store.remove(display.id)
        with patch.object(self.player, "send_packet", side_effect=RuntimeError("busy")):
            self.renderer.removed(display.id)
        self.assertIn(display.id, self.renderer.viewers[self.player.unique_id]["shown"])
        self.renderer.tick()
        self.assertNotIn(display.id, self.renderer.viewers[self.player.unique_id]["shown"])

    def test_missing_custom_addon_hidden_and_warned_once_without_deleting_record(self):
        self.add(block="gone:addon_block")
        self.show()
        for _ in range(5):
            self.renderer.tick()
        self.assertEqual(len(self.logs), 1)
        self.assertEqual(self.server.reads, ["gone:addon_block"])
        self.assertEqual(len(self.store.displays), 1)
        self.assertFalse(self.player.packets)

    def test_payloads_and_ids_are_shared_between_viewers_but_distinct_per_display(self):
        self.add()
        self.add(position=(.5, 64, 5.5))
        second = Player(self.player.dimension)
        second.unique_id = "second-player"
        self.server.online_players.append(second)
        self.show()
        self.assertEqual(self.player.packets, second.packets)
        self.assertNotEqual(self.player.packets[0], self.player.packets[1])
        self.assertEqual(self.server.reads, ["minecraft:stone"])

    def test_send_budget_limits_initial_load_and_finishes_over_following_polls(self):
        self.renderer.SEND_BUDGET = 2
        for i in range(5):
            self.add(position=(i + .5, 64, 3.5))
        self.show()
        self.assertEqual(len(self.player.packets), 2)
        self.renderer.tick()
        self.assertEqual(len(self.player.packets), 4)
        self.renderer.tick()
        self.assertEqual(len(self.player.packets), 5)

    def test_visible_cap_and_negative_grid_coordinates(self):
        self.renderer.MAX_VISIBLE = 2
        for x in (-1, -3, -5):
            self.add(position=(x, 64, 3.5))
        self.show()
        self.assertEqual(len(self.player.packets), 2)
        self.assertEqual(len(self.renderer.index), 1)

    def test_one_failed_viewer_does_not_block_another(self):
        self.add()
        second = Player(self.player.dimension)
        second.unique_id = "second-player"
        self.server.online_players.append(second)
        with patch.object(self.player, "send_packet", side_effect=RuntimeError("closed")):
            self.show()
        self.assertEqual(len(second.packets), 1)
        self.renderer.tick()
        self.assertEqual(len(self.player.packets), 1)

    def test_reload_resolves_block_name_to_new_runtime_id_not_stale_saved_id(self):
        self.add()
        self.show()
        old = self.player.packets[0][1]
        self.renderer.close()
        self.server.create_block_data = lambda name: types.SimpleNamespace(type=name, runtime_id=0xaabbccdd)
        reloaded = rendering.Renderer(self.server, storage.Store(self.path), self.logger)
        reloaded.sync_player(self.player, immediate=True)
        self.assertNotEqual(self.player.packets[-1][1], old)
        self.assertIn(packets.sint(packets.block_variant(0xaabbccdd)), self.player.packets[-1][1])


class PackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="display-packs-", dir=ROOT / "tests")
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.assertTrue(self.root.is_relative_to((ROOT / "tests").resolve(strict=True)))
        self.addCleanup(self.temporary.cleanup)
        (self.root / "server.properties").write_text("level-name=TestWorld\n", encoding="utf-8")
        self.world = self.root / "worlds/TestWorld"
        self.world.mkdir(parents=True)
        self.files = packs.bundled_files()

    def test_bundle_matches_source_and_has_no_scripts(self):
        self.assertEqual(set(self.files), packs.FILES)
        for name, data in self.files.items():
            self.assertEqual((ROOT / name).read_bytes(), data)
        bp = json.loads(self.files["behavior_pack/entities/oak_planks.json"])["minecraft:entity"]
        self.assertEqual(bp["description"]["identifier"], "ed:oak_planks")
        components = bp["components"]
        self.assertFalse(components["minecraft:physics"]["has_gravity"])
        self.assertFalse(components["minecraft:physics"]["has_collision"])
        self.assertEqual(components["minecraft:damage_sensor"]["triggers"], [{"deals_damage": "no"}])
        self.assertIn("minecraft:persistent", components)
        self.assertFalse(any("behavior." in name for name in components))
        cube = json.loads(self.files["resource_pack/models/entity/oak_planks.geo.json"])["minecraft:geometry"][0]["bones"][0]["cubes"][0]
        self.assertEqual(cube["size"], [16, 16, 16])
        self.assertEqual(len(cube["uv"]), 6)

    def test_installs_both_packs_and_preserves_other_pack_entries(self):
        other = {"pack_id": "00000000-0000-0000-0000-000000000001", "version": [9, 0, 0]}
        for name in ("world_behavior_packs.json", "world_resource_packs.json"):
            (self.world / name).write_text(json.dumps([other]), encoding="utf-8")
        original_properties = (self.root / "server.properties").read_bytes()
        self.assertEqual(packs.install_packs(self.root), "installed/updated")
        for _, (pack_id, relative, world_file, _) in packs.PACKS.items():
            self.assertTrue((self.root / relative / "manifest.json").exists())
            self.assertEqual(json.loads((self.world / world_file).read_text()), [other, {"pack_id": pack_id, "version": packs.VERSION}])
        self.assertEqual((self.root / "server.properties").read_bytes(), original_properties)
        self.assertEqual(len(list(self.world.glob("*.entity-displays-backup-*"))), 2)
        self.assertEqual(packs.install_packs(self.root), "unchanged")
        self.assertEqual(len(list(self.world.glob("*.entity-displays-backup-*"))), 2)

    def test_special_model_geometry_and_controller_mappings(self):
        model_data = json.loads(self.files["resource_pack/ed_models.json"])["blocks"]
        shapes = json.loads(self.files["resource_pack/models/entity/model.geo.json"])["minecraft:geometry"]
        shapes = {s["description"]["identifier"].split(".")[-1]: s for s in shapes}
        self.assertEqual(set(shapes), {"chest", "empty", "door_lower", "door_upper"})
        for shape in shapes.values():
            self.assertEqual([b["name"] for b in shape["bones"]], ["yaw", "pitch", "roll", "box"])
        lower, upper = shapes["door_lower"]["bones"][-1]["cubes"][0], shapes["door_upper"]["bones"][-1]["cubes"][0]
        self.assertEqual((lower["origin"][1], upper["origin"][1]), (-8, 0))
        self.assertEqual(lower["size"], [16, 8, 16])
        self.assertEqual(upper["size"], [16, 8, 16])
        self.assertEqual(lower["uv"]["north"]["uv_size"], [16, 16])
        cubes = shapes["chest"]["bones"][-1]["cubes"]
        self.assertEqual(len(cubes), 3)  # Body, lid, latch; not a single cube.
        for axis in range(3):
            self.assertAlmostEqual(min(c["origin"][axis] for c in cubes), -8)
            self.assertAlmostEqual(max(c["origin"][axis] + c["size"][axis] for c in cubes), 8)
        for shape in shapes.values():
            width = shape["description"]["texture_width"]
            for cube in shape["bones"][-1].get("cubes", []):
                for uv in cube["uv"].values():
                    for axis in range(2):
                        self.assertTrue(0 <= uv["uv"][axis] <= width)
                        self.assertTrue(0 <= uv["uv"][axis] + uv["uv_size"][axis] <= width)
        client = json.loads(self.files["resource_pack/entity/model.entity.json"])["minecraft:client_entity"]["description"]
        controls = json.loads(self.files["resource_pack/render_controllers/model.render_controllers.json"])["render_controllers"]
        self.assertEqual(set(client["render_controllers"]), set(controls))
        for index, entry in enumerate(model_data):
            for half, number in (("lower", 0), ("upper", 1)):
                arrays = controls["controller.render.ed.model_" + half]["arrays"]
                expected = "door_" + half if entry["kind"] == "door" else "chest" if number == 0 else "empty"
                self.assertEqual(arrays["geometries"]["Array.shape"][index], "Geometry." + expected)
                alias = arrays["textures"]["Array.skin"][index].split(".")[1]
                self.assertEqual(client["textures"][alias], entry["textures"][number])
        by_name = {e["block"]: e for e in model_data}
        self.assertNotEqual(by_name["minecraft:spruce_door"]["textures"], by_name["minecraft:iron_door"]["textures"])
        self.assertEqual(by_name["minecraft:waxed_copper_door"]["textures"], by_name["minecraft:copper_door"]["textures"])
        bp = json.loads(self.files["behavior_pack/entities/model.json"])["minecraft:entity"]
        self.assertEqual(bp["description"]["identifier"], "ed:model")
        self.assertEqual(list(bp["description"]["properties"]), ["ed:w", "ed:h", "ed:d", "ed:rx", "ed:ry", "ed:rz"])
        self.assertFalse(bp["components"]["minecraft:physics"]["has_collision"])
        self.assertFalse(bp["components"]["minecraft:physics"]["has_gravity"])
        self.assertEqual(bp["components"]["minecraft:damage_sensor"]["triggers"], [{"deals_damage": "no"}])

    def test_corrupt_world_list_fails_before_any_pack_writes(self):
        (self.world / "world_resource_packs.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            packs.install_packs(self.root)
        self.assertFalse((self.root / "behavior_packs").exists())
        self.assertEqual((self.world / "world_resource_packs.json").read_text(), "not json")

    def test_unowned_pack_folder_refused(self):
        directory = self.root / "resource_packs/ed_entity_displays_rp"
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps({"header": {"uuid": "unrelated", "version": [0, 1, 0]}}))
        with self.assertRaises(ValueError):
            packs.install_packs(self.root)
        self.assertFalse((self.root / "behavior_packs").exists())

    def test_newer_owned_pack_refused(self):
        directory = self.root / "resource_packs/ed_entity_displays_rp"
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps({"header": {"uuid": packs.PACKS["resource_pack"][0], "version": [9, 0, 0]}}))
        with self.assertRaises(ValueError):
            packs.install_packs(self.root)

    def test_world_traversal_refused(self):
        (self.root / "server.properties").write_text("level-name=../outside\n")
        with self.assertRaises(ValueError):
            packs.install_packs(self.root)

    def test_unsafe_file_set_refused(self):
        with self.assertRaises(ValueError):
            packs.install_packs(self.root, {"behavior_pack/../../server.properties": b"bad"})

    def test_bad_or_unexpected_zip_refused(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../server.properties", "bad")
        with self.assertRaises(ValueError):
            packs.validate_bundle(stream.getvalue())

    def test_linked_path_refused(self):
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda item: item.name == "resource_packs" or original(item)):
            with self.assertRaises(ValueError):
                packs.install_packs(self.root)
        self.assertFalse((self.root / "behavior_packs").exists())

    def test_duplicate_owned_world_entries_collapsed_without_other_changes(self):
        pack_id = packs.PACKS["behavior_pack"][0]
        other = {"pack_id": "other", "version": [1, 0, 0]}
        entry = {"pack_id": pack_id, "version": [0, 1, 0]}
        path = self.world / "world_behavior_packs.json"
        path.write_text(json.dumps([entry, other, entry]))
        packs.install_packs(self.root)
        self.assertEqual(json.loads(path.read_text()), [{"pack_id": pack_id, "version": packs.VERSION}, other])


if __name__ == "__main__":
    unittest.main()
