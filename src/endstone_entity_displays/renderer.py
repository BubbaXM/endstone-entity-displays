"""Nearby client-only blocks; one sparse visibility poll/second, no world scans."""
import math
import secrets

from . import packets
from .store import block_id
from .catalog import CUBOID_TYPE, MODEL_TYPE, PROPERTIES, load_catalog, load_models, actor_type
from .transforms import centre


class Renderer:
    SHOW_DISTANCE, HIDE_DISTANCE, CELL = 48, 56, 128
    MAX_VISIBLE, SEND_BUDGET = 256, 32

    def __init__(self, server, store, logger):
        if server.protocol_version not in packets.SUPPORTED_PROTOCOLS:
            raise ValueError(f"Block displays do not support protocol {server.protocol_version}; supported: 2193, 2225. No packets sent.")
        self.protocol = server.protocol_version
        self.server, self.store, self.logger = server, store, logger
        self.viewers, self.payloads, self.blocks, self.index = {}, {}, {}, {}
        self.hidden = set()
        self.revision = -1
        self.catalog = load_catalog()
        self.models = load_models()
        self.cuboid_enabled = True
        self.schema_payload = packets.schema(CUBOID_TYPE, PROPERTIES)
        self.schemas = {CUBOID_TYPE: self.schema_payload, MODEL_TYPE: packets.schema(MODEL_TYPE, PROPERTIES)}
        # Separate ID range from both normal actors and the leaderboard plugin.
        self.identifier = (1 << 54) + secrets.randbits(40)

    def resolve(self, name):
        name = block_id(name)
        if name not in self.blocks:
            try:
                data = self.server.create_block_data(name)
                if data is None:
                    raise ValueError("Block not registered.")
                canonical = block_id(str(data.type))
                runtime = packets.block_variant(data.runtime_id)
                self.blocks[name] = canonical, runtime
            except (ValueError, RuntimeError) as error:
                # Bedrock historically calls the oak door wooden_door. Only
                # alias when the requested name is not actually registered.
                if name == "minecraft:oak_door":
                    self.blocks[name] = self.resolve("minecraft:wooden_door")
                    return self.blocks[name]
                raise ValueError(f"Unknown or unavailable block '{name}'. Use its Bedrock block ID; custom blocks need their add-on installed.") from error
        result = self.blocks[name]
        if result is None:
            raise ValueError(f"Block '{name}' is unavailable on this server; check its installed add-on.")
        return result

    def rebuild_index(self):
        if self.revision == self.store.revision:
            return
        self.index = {}
        for display in self.store.displays.values():
            x, _, z = display.position
            key = (display.dimension, math.floor(x / self.CELL), math.floor(z / self.CELL))
            self.index.setdefault(key, []).append(display)
        self.revision = self.store.revision

    def nearby(self, dimension, position):
        self.rebuild_index()
        x, _, z = position
        cx, cz = math.floor(x / self.CELL), math.floor(z / self.CELL)
        # Nine buckets, not a scan of every display or any world entities.
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield from self.index.get((dimension, cx + dx, cz + dz), ())

    def payload(self, display):
        if (display.mode, display.block) in self.hidden:
            return None
        old = self.payloads.get(display.id)
        if old is None or old[2] != display:
            try:
                variant = self.variant(display)
            except ValueError as error:
                self.logger.warning(f"Saved display kept but hidden: {error}")
                self.hidden.add((display.mode, display.block))
                return None
            if old is not None and old[2].mode == display.mode:
                unique, runtime_id = old[3], old[4]
            else:
                self.identifier += 1
                unique, runtime_id = -self.identifier, self.identifier
            self.payloads[display.id] = (packets.add_visual(unique, runtime_id, display, variant, self.protocol),
                                         packets.remove_block(unique), display, unique, runtime_id)
        return self.payloads[display.id]

    def variant(self, display):
        _, runtime = self.resolve(display.block)
        if display.mode == "model":
            if not self.cuboid_enabled:
                raise ValueError("Display model pack is unavailable; check startup logs and restart.")
            if display.block not in self.models:
                raise ValueError(f"No special model for {display.block}; use auto or cuboid mode.")
            return self.models[display.block][0]
        if display.mode == "native" and display.block in self.models:
            raise ValueError(f"{display.block} needs its special display model; use /ed mode auto.")
        if display.mode == "cuboid":
            if not self.cuboid_enabled:
                raise ValueError("Cuboid pack is unavailable; check startup logs and restart.")
            if display.block not in self.catalog:
                raise ValueError(f"No cuboid texture mapping for {display.block}; use native mode or add a mapping and rebuild the RP.")
            return self.catalog[display.block]
        return runtime

    def hide(self, player, viewer, key):
        player.send_packet(packets.REMOVE_ACTOR, viewer["shown"][key])
        del viewer["shown"][key]
        viewer["versions"].pop(key, None)

    def deliver(self, player, viewer, display):
        payload = self.payload(display)
        if payload is None:
            return
        kind = actor_type(display)
        if display.mode != "native" and kind not in viewer["schemas"]:
            player.send_packet(packets.SYNC_ACTOR_PROPERTY, self.schemas[kind])
            viewer["schemas"].add(kind)
        previous = viewer["versions"].get(display.id)
        if previous is not None and previous.mode != display.mode:
            self.hide(player, viewer, display.id)
            previous = None
        if previous is None:
            player.send_packet(packets.ADD_ACTOR, payload[0])
            viewer["shown"][display.id] = payload[1]
        else:
            runtime_id = payload[4]
            if previous.position != display.position or previous.size[1] != display.size[1]:
                player.send_packet(packets.MOVE_ACTOR, packets.move_visual(runtime_id, display))
            if (previous.block, previous.size, previous.rotation) != (display.block, display.size, display.rotation):
                player.send_packet(packets.SET_ACTOR_DATA, packets.update_visual(runtime_id, display, self.variant(display)))
        # Do not acknowledge partially failed updates: the next poll retries.
        viewer["versions"][display.id] = display

    def changed(self, display_id):
        display = self.store.displays.get(display_id)
        if display is None:
            self.removed(display_id)
            return
        # Immediate updates to existing viewers; new nearby viewers are found
        # by the normal visibility poll. No repeated world/actor scans.
        for player in self.server.online_players:
            viewer = self.viewers.get(str(player.unique_id))
            if viewer and display_id in viewer["shown"]:
                try:
                    if player.dimension.type.value != display.dimension:
                        self.hide(player, viewer, display_id)
                    else:
                        self.deliver(player, viewer, display)
                except Exception as error:
                    self.logger.error(f"Display update will retry on next poll: {error}")

    def reset(self, player):
        key = str(player.unique_id)
        viewer = self.viewers.get(key)
        if viewer:
            for display_id in list(viewer["shown"]):
                self.hide(player, viewer, display_id)
        self.viewers.pop(key, None)

    def forget(self, player):
        self.viewers.pop(str(player.unique_id), None)

    def sync_player(self, player, immediate=False):
        if player.is_dead:
            self.reset(player)
            return
        dimension = player.dimension.type.value
        key = str(player.unique_id)
        viewer = self.viewers.get(key)
        if viewer is not None and viewer["dimension"] != dimension:
            self.reset(player)
            viewer = None
        if viewer is None:
            viewer = {"dimension": dimension, "shown": {}, "versions": {}, "schemas": set(), "age": 0}
            self.viewers[key] = viewer
        viewer["age"] += 1
        if viewer["age"] < 2 and not immediate:
            return  # Allow join/dimension/respawn handshakes to finish.
        location = player.location
        position = (location.x, location.y, location.z)
        candidates = []
        for display in self.nearby(dimension, position):
            center = centre(display.position, display.size)
            distance = sum((center[i] - position[i]) ** 2 for i in range(3))
            radius = math.sqrt(sum(v * v for v in display.size)) / 2
            limit = self.HIDE_DISTANCE if display.id in viewer["shown"] else self.SHOW_DISTANCE
            if distance <= (limit + radius) ** 2:
                candidates.append((distance, display.id, display))
        candidates.sort(key=lambda item: (item[0], item[1]))
        candidates = candidates[:self.MAX_VISIBLE]
        desired = {display.id for _, _, display in candidates}
        for display_id in list(viewer["shown"]):
            if display_id not in desired:
                self.hide(player, viewer, display_id)
        sent = 0
        for _, _, display in candidates:
            if viewer["versions"].get(display.id) == display:
                continue
            if sent >= self.SEND_BUDGET:
                break
            self.deliver(player, viewer, display)
            sent += 1

    def tick(self):
        if not self.store.displays and not self.viewers:
            return
        online = set()
        for player in self.server.online_players:
            online.add(str(player.unique_id))
            try:
                self.sync_player(player)
            except Exception as error:
                # One viewer's disconnect cannot stop visibility for other players.
                self.logger.error(f"Could not sync block displays for a viewer: {error}")
        self.viewers = {key: value for key, value in self.viewers.items() if key in online}
        for key in list(self.payloads):
            if key not in self.store.displays:
                del self.payloads[key]

    def removed(self, display_id):
        # Called only after the deletion is durably saved.
        for player in self.server.online_players:
            viewer = self.viewers.get(str(player.unique_id))
            if viewer and display_id in viewer["shown"]:
                try:
                    self.hide(player, viewer, display_id)
                except Exception as error:
                    self.logger.error(f"Display removal will be retried on next poll: {error}")
        self.payloads.pop(display_id, None)

    def close(self):
        for player in self.server.online_players:
            try:
                self.reset(player)
            except Exception as error:
                self.logger.error(f"Could not remove a departing display visual: {error}")
        self.viewers.clear()
        self.payloads.clear()
