from pathlib import Path
import math

from endstone import Player
from endstone.event import (event_handler, PlayerJoinEvent, PlayerQuitEvent,
                            PlayerRespawnEvent, PlayerDimensionChangeEvent)
from endstone.plugin import Plugin

from .packs import install_packs
from .placement import REACH, cube_distance, first_block, spawn_position, view_ray
from .renderer import Renderer
from .store import BOUNDS, Store, block_id
from .api import DisplayAPI
from .transforms import ray_distance
from .spider import create_spider

ENTITY_TYPE = "ed:oak_planks"
PERMISSION = "entitydisplays.admin"


class EntityDisplaysPlugin(Plugin):
    api_version = "0.11"
    prefix = "Entity Displays"
    commands = {"ed": {"description": "Create or remove a visual block display.",
                       "aliases": ["entitydisplay"], "usages": ["/ed <action: str> <x: float> <y: float> <z: float>",
                                                                   "/ed <action: str> <factor: float>",
                                                                   "/ed <action: str> <value: str>", "/ed [action: str]"],
                       "permissions": [PERMISSION]}}
    permissions = {PERMISSION: {"description": "Create and remove display entities.", "default": "op"}}

    def on_load(self):
        # File-only startup work before Bedrock loads the world's pack stack.
        self.pack_error = ""
        try:
            result = install_packs(Path.cwd())
            self.logger.info(f"Bundled display packs: {result}")
        except Exception as error:
            self.pack_error = str(error)
            self.logger.error(f"Display pack setup failed: {error}. Special models and cuboids need this pack; ordinary native blocks do not.")

    def on_enable(self):
        self.ready, self.renderer, self.task, self.api = False, None, None, None
        self.selected = {}
        self.spider_demos = {}
        try:
            self.store = Store(self.data_folder / "displays.json")
            self.renderer = Renderer(self.server, self.store, self.logger)
            self.renderer.cuboid_enabled = not bool(getattr(self, "pack_error", ""))
            self.api = DisplayAPI(self, self.store, self.renderer)
            upgraded = self.api.upgrade_saved_models()
            if upgraded:
                self.logger.info(f"Upgraded {upgraded} saved door/chest displays to special models (saved on next edit).")
            self.register_events(self)
            self.ready = True
            self.start_polling()
            self.logger.info("Ready: /ed create <namespace:block>, /ed remove. Saved block displays: " + str(len(self.store.displays)))
        except Exception as error:
            self.ready = False
            self.logger.error(f"Block displays disabled; existing data preserved: {error}")

    def start_polling(self):
        if (self.store.displays or any(v["shown"] for v in self.renderer.viewers.values())) and self.task is None:
            self.task = self.server.scheduler.run_task(self, self.poll, delay=20, period=20)

    def poll(self):
        self.renderer.tick()
        self.stop_if_empty()

    def stop_if_empty(self):
        # Keep retrying undelivered removals even after the last saved block is
        # deleted. Stopping early could strand a client-only ghost entity.
        if self.task and not self.store.displays and not any(v["shown"] for v in self.renderer.viewers.values()):
            self.task.cancel()
            self.task = None
            self.renderer.viewers.clear()

    def on_disable(self):
        self.ready = False
        if getattr(self, "api", None):
            self.api.close()
        self.selected = {}
        self.spider_demos = {}
        if getattr(self, "task", None):
            self.task.cancel()
            self.task = None
        if getattr(self, "renderer", None):
            self.renderer.close()  # Saved displays and legacy world actors stay.

    @event_handler
    def on_join(self, event: PlayerJoinEvent):
        if self.renderer:
            self.renderer.forget(event.player)

    @event_handler
    def on_quit(self, event: PlayerQuitEvent):
        player_id = str(event.player.unique_id)
        self.selected.pop(player_id, None)
        demo = self.spider_demos.pop(player_id, None)
        if demo and self.ready:
            demo.remove()
        if self.renderer:
            self.renderer.forget(event.player)

    @event_handler
    def on_respawn(self, event: PlayerRespawnEvent):
        if self.renderer:
            self.renderer.reset(event.player)

    @event_handler
    def on_dimension_change(self, event: PlayerDimensionChangeEvent):
        if self.renderer:
            self.renderer.reset(event.player)

    def aimed(self, player):
        origin, direction = view_ray(player.location, player.is_sneaking)
        dimension = player.dimension
        bounds = BOUNDS.get(dimension.type.value)
        if bounds is None:
            raise ValueError("Unsupported display dimension.")
        def block_at(x, y, z):
            return dimension.get_block_at(x, y, z).type if bounds[0] <= y < bounds[1] else "minecraft:barrier"
        obstruction = first_block(origin, direction, block_at)
        nearest = min(REACH, obstruction[2]) if obstruction else REACH
        identity = None
        for display in self.renderer.nearby(dimension.type.value, origin):
            distance = ray_distance(origin, direction, display.position, display.size, display.rotation)
            if distance is not None and distance <= nearest + 1e-6:
                identity, nearest = display.id, distance
        if identity is None:
            raise ValueError("Aim at a new block display within 6 blocks, or /ed select <id>.")
        return identity

    def edit(self, player, action, args):
        player_id = str(player.unique_id)
        if action == "spider":
            if args and args != ["remove"]:
                raise ValueError("Usage: /ed spider or /ed spider remove")
            previous = self.spider_demos.get(player_id)
            if args:
                if previous is None:
                    raise ValueError("You have no spider demo to remove.")
                previous.remove()
                del self.spider_demos[player_id]
                if self.selected.get(player_id) in previous.parts:
                    self.selected.pop(player_id, None)
                player.send_message("§aRemoved your spider display demo.")
                return
            location = player.location
            angle = math.radians(location.yaw)
            origin = (location.x - math.sin(angle) * 4.5, location.y,
                      location.z + math.cos(angle) * 4.5)
            # Build first so a failed creation leaves the previous demo intact.
            demo = create_spider(self.api, origin, dimension=player.dimension.type.value, yaw=-location.yaw)
            if previous:
                previous.remove()
            self.spider_demos[player_id] = demo
            self.selected[player_id] = demo.body_id
            try:
                self.renderer.sync_player(player, immediate=True)
            except Exception as error:
                self.logger.error(f"Spider created; visual delivery will retry: {error}")
            player.send_message("§aCreated a 20-part spider display demo in front of you (body selected).\n§7Static display, not a mob. /ed spider remove cleans it up; it also disappears when you leave/restart.")
            return
        if action == "list":
            if args:
                raise ValueError("Usage: /ed list")
            records = self.api.list(dimension=player.dimension.type.value)
            lines = [f"§e{len(records)} displays in this dimension (showing first 20):"]
            lines += [f"§f{h.id[:8]} §7{h.snapshot.block} {h.snapshot.size}" for h in records[:20]]
            player.send_message("\n".join(lines))
            return
        if action == "select":
            if len(args) > 1:
                raise ValueError("Usage: /ed select [display-id]")
            handle = self.api.get(args[0] if args else self.aimed(player))
            if handle is None:
                raise ValueError("Display not found.")
            self.selected[player_id] = handle.id
            player.send_message(f"§aSelected {handle.id[:8]} ({handle.snapshot.block}).")
            return
        counts = {"info": 0, "move": 3, "offset": 3, "size": 3, "rotate": 3, "scale": 1,
                  "block": 1, "mode": 1, "clone": 0}
        if action not in counts or len(args) != counts[action]:
            raise ValueError("Use /ed move|offset|size|rotate <x> <y> <z>, /ed scale <factor>, /ed block <id>, /ed mode auto|native|cuboid|model, /ed info or /ed clone.")
        selected = self.selected.get(player_id)
        handle = self.api.get(selected) if selected else None
        if handle is None:
            handle = self.api.get(self.aimed(player))
            self.selected[player_id] = handle.id
        if action in {"move", "offset", "size", "rotate", "scale"}:
            try:
                numbers = [float(v) for v in args]
            except ValueError:
                raise ValueError("Use numeric values for movement, size and rotation.") from None
            {"move": handle.move_to, "offset": handle.translate, "size": handle.resize,
             "rotate": handle.rotate, "scale": handle.scale}[action](*numbers)
        elif action == "block":
            handle.set_block(args[0])
        elif action == "mode":
            handle.update(mode=args[0])
        elif action == "clone":
            x, y, z = handle.position
            handle = handle.clone(position=(x + 1, y, z))
            self.selected[player_id] = handle.id
        record = handle.snapshot
        player.send_message(f"§a{record.id[:8]} §f{record.block}\n§7position={record.position} size={record.size}\nrotation={record.rotation} mode={record.mode}")

    def on_command(self, sender, command, args):
        if command.name.lower() not in {"ed", "entitydisplay"}:
            return False
        try:
            if not isinstance(sender, Player):
                raise ValueError("Use /ed in-game.")
            if not sender.has_permission(PERMISSION):
                raise ValueError("Missing entitydisplays.admin permission.")
            if not self.ready:
                raise ValueError("Block displays are unavailable; check the server startup log.")
            action = args[0].lower() if args else "create"
            if action not in {"create", "remove", "help"}:
                self.edit(sender, action, args[1:])
                return True
            if len(args) > 2 or action == "help" and len(args) != 1:
                raise ValueError("Usage: /ed create <namespace:block> or /ed remove")
            if action == "help":
                sender.send_message("§e/ed create <namespace:block> | /ed remove [id]\n/ed select [id] | /ed list | /ed info\n/ed move <x> <y> <z> | /ed offset <dx> <dy> <dz>\n/ed size <width> <height> <depth> | /ed scale <factor>\n/ed rotate <x> <y> <z> | /ed block <namespace:block>\n/ed mode auto|native|cuboid|model | /ed clone\n/ed spider | /ed spider remove\n§7Edits use your selected display. Doors/chests use special display-only RP models.")
                return True
            if action == "remove" and len(args) == 2:
                self.api.remove(args[1])
                sender.send_message("§aRemoved the block display.")
                return True
            # Resolve through the server registry before any world queries or
            # writes. The model/texture catalogs never make an unknown ID valid.
            if action == "create":
                requested = block_id(args[1] if len(args) == 2 else "minecraft:oak_planks")
                canonical, _ = self.renderer.resolve(requested)
            origin, direction = view_ray(sender.location, sender.is_sneaking)
            dimension = sender.dimension
            dimension_id = dimension.type.value
            bounds = BOUNDS.get(dimension_id)
            if bounds is None:
                raise ValueError("Custom dimensions are not supported by this prototype.")
            def block_at(x, y, z):
                if not bounds[0] <= y < bounds[1] or max(abs(x), abs(z)) > 29_999_980:
                    return "minecraft:barrier"
                return dimension.get_block_at(x, y, z).type
            if action == "create":
                size = self.renderer.models.get(canonical, (None, (1, 1, 1)))[1]
                x, y, z = spawn_position(origin, direction, block_at, size)
                if not bounds[0] <= y <= bounds[1] - 1 or max(abs(x), abs(z)) > 29_999_980:
                    raise ValueError("That display position is outside the supported world bounds.")
                handle = self.api.create(canonical, (x, y, z), dimension=dimension_id)
                self.selected[str(sender.unique_id)] = handle.id
                try:
                    self.renderer.sync_player(sender, immediate=True)
                except Exception as error:
                    self.logger.error(f"Display {handle.id} saved; visual delivery will retry: {error}")
                sender.send_message(f"§aCreated {canonical} display {handle.id[:8]} at {x:.2f}, {y:.2f}, {z:.2f} (selected).")
            else:
                obstruction = first_block(origin, direction, block_at)
                limit = min(REACH, obstruction[2]) if obstruction else REACH
                candidate, saved_id, nearest = None, None, limit + 1e-6
                for display in self.renderer.nearby(dimension_id, origin):
                    distance = ray_distance(origin, direction, display.position, display.size, display.rotation)
                    if distance is not None and distance <= nearest:
                        saved_id, nearest = display.id, distance
                # One command-time scan, never a polling loop or retained Actor.
                # Preserve removal of oak entities made by version 0.1.0.
                for actor in dimension.actors:
                    if actor.type != ENTITY_TYPE or not actor.is_valid or actor.is_dead:
                        continue
                    location = actor.location
                    distance = cube_distance(origin, direction, (location.x, location.y, location.z))
                    if distance is not None and distance <= nearest:
                        candidate, saved_id, nearest = actor, None, distance
                if saved_id is not None:
                    self.api.remove(saved_id)
                elif candidate is not None:
                    candidate.remove()
                else:
                    raise ValueError("Aim at a block display within 6 blocks, with no wall in the way.")
                sender.send_message("§aRemoved the block display.")
        except ValueError as error:
            sender.send_error_message(str(error))
        except Exception as error:
            self.logger.error(f"Display command failed: {error}")
            sender.send_error_message("Display command failed. Check the server log; saved display data is preserved.")
        return True
