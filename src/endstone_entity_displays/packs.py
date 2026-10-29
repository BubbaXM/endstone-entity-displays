"""File-only, idempotent setup of this plugin's bundled BP + RP at startup."""
import hashlib
from importlib import resources
import io
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from uuid import uuid4
import zipfile

VERSION = [0, 2, 1]
PACKS = {
    "behavior_pack": ("01c7ead0-95fe-4879-913a-d17d22e2d9e6", "behavior_packs/ed_entity_displays_bp", "world_behavior_packs.json", "data"),
    "resource_pack": ("00cf0fbe-3f16-426c-9faa-8803a6c051b0", "resource_packs/ed_entity_displays_rp", "world_resource_packs.json", "resources")
}
FILES = frozenset({"behavior_pack/manifest.json", "behavior_pack/entities/oak_planks.json",
                   "behavior_pack/loot_tables/entities/ed_empty.json", "resource_pack/manifest.json",
                   "resource_pack/entity/oak_planks.entity.json", "resource_pack/models/entity/oak_planks.geo.json",
                   "resource_pack/render_controllers/oak_planks.render_controllers.json",
                   "behavior_pack/entities/cuboid.json", "resource_pack/ed_catalog.json",
                   "resource_pack/entity/cuboid.entity.json", "resource_pack/models/entity/cuboid.geo.json",
                   "resource_pack/animations/cuboid.animation.json",
                   "resource_pack/render_controllers/cuboid.render_controllers.json",
                   "behavior_pack/entities/model.json", "resource_pack/ed_models.json",
                   "resource_pack/entity/model.entity.json", "resource_pack/models/entity/model.geo.json",
                   "resource_pack/render_controllers/model.render_controllers.json"})


def validate_bundle(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) != len(FILES) or {entry.orig_filename for entry in entries} != FILES:
            raise ValueError("Unexpected or duplicate display pack files.")
        if sum(entry.file_size for entry in entries) > 2 * 1024 * 1024:
            raise ValueError("Display pack archive is too large.")
        for entry in entries:
            name, path = entry.orig_filename, PurePosixPath(entry.orig_filename)
            if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or entry.flag_bits & 1:
                raise ValueError("Unsafe display pack path.")
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Symlink in display pack archive.")
        if archive.testzip() is not None:
            raise ValueError("Display pack archive checksum failed.")
        files = {name: archive.read(name) for name in FILES}
    for name, content in files.items():
        json.loads(content)
    for prefix, (pack_id, _, _, kind) in PACKS.items():
        manifest = json.loads(files[prefix + "/manifest.json"])
        if (manifest["header"]["uuid"] != pack_id or manifest["header"]["version"] != VERSION or
                len(manifest["modules"]) != 1 or manifest["modules"][0]["type"] != kind):
            raise ValueError("Wrong display pack manifest.")
    return files


def bundled_files():
    assets = resources.files("endstone_entity_displays").joinpath("assets")
    data = assets.joinpath("display_packs.zip").read_bytes()
    index = json.loads(assets.joinpath("pack_index.json").read_text(encoding="utf-8"))
    if index.get("version") != VERSION or index.get("sha256") != hashlib.sha256(data).hexdigest():
        raise ValueError("Bundled display packs changed or are missing; rebuild the plugin assets.")
    return validate_bundle(data)


def safe_path(root, path):
    if not path.resolve().is_relative_to(root):
        raise ValueError("Display pack path escapes the server folder.")
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Refusing linked display pack paths.")
    return path


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".ed-pack-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)  # Only the exact temporary file created above.


def install_packs(server_root, files=None):
    files = bundled_files() if files is None else files
    if set(files) != FILES:
        raise ValueError("Unexpected display pack files.")
    root = Path(server_root).resolve(strict=True)
    properties = (root / "server.properties").read_text(encoding="utf-8-sig")
    levels = [line.partition("=")[2].strip() for line in properties.splitlines() if line.startswith("level-name=")]
    if len(levels) != 1 or not levels[0] or levels[0] in {".", ".."} or any(c in levels[0] for c in "/\\:"):
        raise ValueError("Invalid or missing level-name in server.properties.")
    world = safe_path(root, root / "worlds" / levels[0])
    writes, lists = [], []
    # Preflight both pack ownership and both world lists before writing anything.
    for prefix, (pack_id, relative, world_file, _) in PACKS.items():
        directory = safe_path(root, root / relative)
        manifest_path = safe_path(root, directory / "manifest.json")
        if directory.exists():
            if not manifest_path.is_file():
                raise ValueError(f"Refusing an unowned pack folder: {directory.name}")
            existing = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if existing["header"]["uuid"] != pack_id:
                raise ValueError("Refusing to replace another plugin's pack.")
            if tuple(existing["header"]["version"]) > tuple(VERSION):
                raise ValueError("Newer display pack is installed; refusing downgrade.")
        for name, content in sorted(files.items(), key=lambda item: (not item[0].endswith("/manifest.json"), item[0])):
            if name.startswith(prefix + "/"):
                target = safe_path(root, directory / name[len(prefix) + 1:])
                if not target.exists() or target.read_bytes() != content:
                    writes.append((target, content))
        target = safe_path(root, world / world_file)
        original = target.read_bytes() if target.exists() else None
        entries = json.loads(original.decode("utf-8-sig")) if original else []
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError(f"Invalid {world_file}; original data preserved.")
        replacement = {"pack_id": pack_id, "version": VERSION}
        indices = [i for i, entry in enumerate(entries) if entry.get("pack_id") == pack_id]
        updated = list(entries)
        if not indices:
            updated.append(replacement)
        else:
            updated[indices[0]] = replacement
            updated = [entry for i, entry in enumerate(updated) if i not in indices[1:]]
        if updated != entries:
            backup = safe_path(root, target.with_name(target.name + ".entity-displays-backup-" + uuid4().hex))
            lists.append((target, original, backup, (json.dumps(updated, indent=2) + "\n").encode("utf-8")))
    for path, data in writes:
        atomic_write(path, data)
    for path, original, backup, data in lists:
        if original is not None:
            atomic_write(backup, original)
        atomic_write(path, data)
    return "installed/updated" if writes or lists else "unchanged"
