"""Public main-thread API. Handles retain IDs, never native Actor/Player objects."""
import threading
from uuid import uuid4

from .store import validate_record
from .transforms import size_vector, rotation_vector


class DisplayAPI:
    api_version = 1

    def __init__(self, plugin, store, renderer):
        self._plugin, self._store, self._renderer = plugin, store, renderer
        self._thread, self._active = threading.get_ident(), True

    def _check(self):
        if not self._active:
            raise RuntimeError("Entity Displays is disabled; obtain its API again after enable.")
        if threading.get_ident() != self._thread:
            raise RuntimeError("Display API must run on the server thread. Schedule with server.scheduler.run_task.")

    def _id(self, key):
        self._check()
        if isinstance(key, DisplayHandle):
            if key._api is not self:
                raise ValueError("Display handle belongs to a different API instance.")
            key = key.id
        if not isinstance(key, str) or not 8 <= len(key) <= 32:
            raise ValueError("Use the display's full ID or an unambiguous prefix of at least 8 characters.")
        if key in self._store.displays:
            return key
        matches = [i for i in self._store.displays if i.startswith(key)]
        if len(matches) > 1:
            raise ValueError("Display ID prefix is ambiguous; use more characters.")
        return matches[0] if matches else None

    def _record(self, key):
        identity = self._id(key)
        if identity is None:
            raise ValueError("Display no longer exists.")
        return self._store.displays[identity]

    def _prepare(self, data, auto=False):
        canonical, _ = self._renderer.resolve(data["block"])
        data["block"] = canonical
        model = self._renderer.models.get(canonical)
        default_size = model[1] if model and (auto or data.get("mode") == "model") else (1, 1, 1)
        data["size"] = size_vector(default_size if data.get("size") is None else data["size"])
        data["rotation"] = rotation_vector(data.get("rotation", (0, 0, 0)))
        if auto:
            transformed = any(data["rotation"]) or data["size"] != (1, 1, 1)
            data["mode"] = "model" if model else "cuboid" if transformed else "native"
        display = validate_record(data)
        self._renderer.variant(display)  # Reject unavailable models/textures before any mutation.
        return display

    def create(self, block, position, *, dimension=0, size=None, rotation=(0, 0, 0), mode="auto", persistent=True):
        self._check()
        data = {"id": uuid4().hex, "block": block, "dimension": dimension, "position": position,
                "size": size, "rotation": rotation, "mode": mode, "persistent": persistent}
        display = self._prepare(data, auto=mode == "auto")
        self._store.put(display, save=persistent)
        self._plugin.start_polling()
        return DisplayHandle(self, display.id)

    def get(self, key):
        identity = self._id(key)
        return DisplayHandle(self, identity) if identity is not None else None

    def list(self, *, dimension=None):
        self._check()
        return tuple(DisplayHandle(self, d.id) for d in self._store.displays.values()
                     if dimension is None or d.dimension == dimension)

    def update(self, key, *, save=True, **changes):
        original = self._record(key)
        if set(changes) - {"block", "position", "dimension", "size", "rotation", "mode", "persistent"}:
            raise ValueError("Unknown display field.")
        if type(save) is not bool:
            raise ValueError("save must be a boolean.")
        data = original.encode()
        data.update(changes)
        auto = data["mode"] == "auto" or ("mode" not in changes and original.mode in {"native", "model"})
        if auto and original.mode == "native" and "size" not in changes and original.size == (1, 1, 1):
            data["size"] = None
        display = self._prepare(data, auto=auto)
        if display == original:
            return DisplayHandle(self, display.id)
        self._store.put(display, save=save and (original.persistent or display.persistent))
        self._renderer.changed(display.id)
        self._plugin.start_polling()
        return DisplayHandle(self, display.id)

    def remove(self, key):
        record = self._record(key)
        self._store.remove(record.id, save=record.persistent)
        self._renderer.removed(record.id)
        self._plugin.stop_if_empty()

    def clone(self, key, **changes):
        record = self._record(key)
        data = record.encode()
        data.pop("id")
        data.update(changes)
        block, position = data.pop("block"), data.pop("position")
        return self.create(block, position, **data)

    def flush(self):
        """Save current persistent displays; temporary displays are always omitted."""
        self._check()
        self._store.commit(self._store.displays)

    def upgrade_saved_models(self):
        """Upgrade old native doors/chests in memory; no startup disk rewrite.

        A model that cannot fit world bounds is left intact, hidden with a
        warning by the renderer, rather than deleting or moving user records.
        """
        self._check()
        upgraded = 0
        for original in tuple(self._store.displays.values()):
            if original.mode != "native" or original.block not in self._renderer.models:
                continue
            try:
                data = original.encode()
                data["size"] = None
                display = self._prepare(data, auto=True)
                self._store.put(display, save=False)
                upgraded += 1
            except ValueError as error:
                self._plugin.logger.warning(f"Saved special display {original.id[:8]} kept unchanged: {error}")
        return upgraded

    def close(self):
        self._active = False


class DisplayHandle:
    def __init__(self, api, identity):
        self._api, self.id = api, identity

    @property
    def snapshot(self):
        return self._api._record(self.id)

    @property
    def position(self):
        return self.snapshot.position

    @property
    def size(self):
        return self.snapshot.size

    @property
    def width(self):
        return self.size[0]

    @width.setter
    def width(self, value):
        self.resize(value, self.height, self.depth)

    @property
    def height(self):
        return self.size[1]

    @height.setter
    def height(self, value):
        self.resize(self.width, value, self.depth)

    @property
    def depth(self):
        return self.size[2]

    @depth.setter
    def depth(self, value):
        self.resize(self.width, self.height, value)

    def move_to(self, x, y, z, *, dimension=None, save=True):
        changes = {"position": (x, y, z)}
        if dimension is not None:
            changes["dimension"] = dimension
        return self.update(save=save, **changes)

    def translate(self, dx, dy, dz, *, save=True):
        x, y, z = self.position
        return self.move_to(x + dx, y + dy, z + dz, save=save)

    def resize(self, width, height, depth, *, save=True):
        return self.update(size=(width, height, depth), save=save)

    def scale(self, amount, *, save=True):
        if type(amount) not in (int, float) or amount <= 0:
            raise ValueError("Scale factor must be a positive finite number.")
        width, height, depth = self.size
        return self.resize(width * amount, height * amount, depth * amount, save=save)

    def rotate(self, x, y, z, *, save=True):
        return self.update(rotation=(x, y, z), save=save)

    def set_block(self, block, *, save=True):
        return self.update(block=block, save=save)

    def update(self, *, save=True, **changes):
        return self._api.update(self.id, save=save, **changes)

    def clone(self, **changes):
        return self._api.clone(self.id, **changes)

    def remove(self):
        return self._api.remove(self.id)
