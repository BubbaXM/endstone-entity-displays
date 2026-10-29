# Entity Displays

Version **0.2.2** · Endstone plugin name: `entity_displays` · Command: `/ed`

Create decorative block displays in Minecraft Bedrock, then move, resize and
rotate them through commands or another plugin's Python code. The visuals are
client-only entities sent through Endstone packets: they do not place blocks,
run falling-block physics or become normal mobs in the world.

This is a Bedrock approximation of Java-style block displays, not Java's
`block_display` entity or its full API. It includes dedicated closed chest and
full-height door models, a temporary 20-part spider demo, persistent display
storage, and a main-thread API for your own models and animations.

## Contents

- [Requirements and compatibility](#requirements-and-compatibility)
- [Installation and upgrades](#installation-and-upgrades)
- [Quick start](#quick-start)
- [Commands and permissions](#commands-and-permissions)
- [Placement, selection and transforms](#placement-selection-and-transforms)
- [Render modes and block support](#render-modes-and-block-support)
- [Door and chest models](#door-and-chest-models)
- [Spider demo](#spider-demo)
- [Python API](#python-api)
- [Animation and multi-part scenes](#animation-and-multi-part-scenes)
- [Persistence and backups](#persistence-and-backups)
- [Performance and limits](#performance-and-limits)
- [Troubleshooting](#troubleshooting)
- [Building and validating releases](#building-and-validating-releases)
- [Known limitations](#known-limitations)

## Requirements and compatibility

| Component | Requirement / release target |
| --- | --- |
| Server | Endstone-enabled Minecraft Bedrock Dedicated Server |
| Endstone API | `0.11`; server target Endstone `0.11.15` |
| Bedrock target | Bedrock `26.50–26.52` and `26.60` |
| Network protocol | **2193 and 2225**, selected from the server |
| Python metadata | Python `>=3.10`; use the interpreter required by your Endstone installation |
| Client packs | Bundled RP required for cuboids, special models and the spider |
| Command access | In-game player with `entitydisplays.admin`, operators by default |
| Other plugins | None required; optional consumers can depend on `entity_displays` |

Version 0.2.2 adds the optional block-passenger trailer required by
[26.60 AddActor](https://mojang.github.io/bedrock-protocol-docs/1.26.60/packets/add-actor-packet/)
for native blocks, cuboids and special models. Existing saved displays and packs
are preserved. Restart the server after installing. Packet fixtures pass for both
protocols; client rendering requires an in-game smoke test.

The codec refuses unsupported protocols instead of guessing packet formats.
A universal `py3-none-any` wheel tag describes the Python package, **not**
compatibility with every Bedrock version or platform. Do not change the protocol
allowlist just to bypass the check: validate the wire format for the new server.

Automated checks cover serialization, API behavior, persistence, pack references
and lifecycle logic. They do not prove that every block renders correctly on
every client. Final orientation, textures and unusual shapes still need an
in-game smoke test. Native API validation here used Windows; other hosts are
not separately certified.

## Installation and upgrades

### Wheel contents

The release file is `endstone_entity_displays-0.2.2-py3-none-any.whl`.

It contains the Python plugin, its Endstone entry point, an embedded BP/RP ZIP,
a SHA-256 pack index, this README as package documentation, and this README as
the wheel's long-description metadata. The pack ZIP contains 18 JSON files.
No separate pack download or Script API add-on is needed. Models reference
vanilla texture paths; the wheel does not redistribute vanilla PNG files.

The wheel has no pip runtime dependencies. It still requires the Endstone
runtime provided by the server; it is not a standalone Python application.

### Fresh wheel installation

1. Stop the server normally and back up its configuration and world.
2. Check that this plugin is not already registered by a wheel or direct
   installation. See the migration notes below if it is.
3. Put the wheel in the server's `plugins` directory. Leave it as a `.whl`;
   do not rename it or manually unpack it into `plugins`.
4. Start from the server directory, with `server.properties` in the working
   directory. Endstone discovers and installs Python plugin wheels.
5. Check for `Bundled display packs: installed/updated` or `unchanged`, followed
   by the plugin's `Ready` message. Investigate pack/protocol errors first.
6. Join with a compatible client and accept the server resource pack.
7. As an operator, use `/ed help`, then create a basic display with `/ed`.

Pack installation runs in `on_load`, before the normal world pack stack loads.
Use a normal restart for pack changes; hot reload is not supported for updating
packs. If your host loads plugins after world packs, check its startup order
and restart again after the pack files have been installed.

### Automatically installed files

Paths are relative to the server directory:

```text
behavior_packs/ed_entity_displays_bp/
resource_packs/ed_entity_displays_rp/
worlds/<level-name>/world_behavior_packs.json
worlds/<level-name>/world_resource_packs.json
plugins/entity_displays/displays.json       # Created on persistent save
```

The plugin reads `level-name` from `server.properties`; it does not modify that
file or force a pack-acceptance setting. Clients must receive and accept the RP.
Custom block add-ons still require their own defining packs.

| Pack | Header UUID | Version |
| --- | --- | --- |
| BP | `01c7ead0-95fe-4879-913a-d17d22e2d9e6` | `0.2.1` |
| RP | `00cf0fbe-3f16-426c-9faa-8803a6c051b0` | `0.2.1` |

Setup compares file bytes and is idempotent. It preserves other pack-list
entries/order, updates/collapses only its own UUID entries, and backs up changed
world lists as `<filename>.entity-displays-backup-<unique-id>`. It refuses
unowned pack folders, newer installed packs, unsafe paths and linked targets.
Do not bypass an ownership error by overwriting another pack's directory.

If pack setup fails, ordinary native blocks may still render, but cuboids and
special models are refused. Fix the logged cause and restart normally.

### Upgrading an existing wheel installation

Stop the server, back up `plugins/entity_displays/displays.json` and retain the
previous release. Keep only the intended wheel version in `plugins`, not
several Entity Displays wheels. Follow your Endstone host's Python plugin
upgrade procedure and verify exactly one `entity_displays` registration.

The Endstone 0.11 loader also scans already-installed Python entry points.
Copying a wheel over a direct registration is not a reliable migration/reinstall
procedure, especially when both have the same version number.

### Migrating from the direct installer to a wheel

While the server is stopped:

1. Back up display data, owned pack folders and both world pack lists.
2. Locate the old package and matching distribution metadata. This project's
   direct installer uses `plugins/.local/endstone_entity_displays` and
   `plugins/.local/endstone_entity_displays-<version>.dist-info`. Other Python
   layouts may use a `site-packages` subdirectory.
3. Move **only this plugin's** old package and metadata to a recoverable backup
   outside Python discovery paths and the top-level wheel scan. Do not move all
   of `.local`, other plugins, the world or `plugins/entity_displays` data.
4. Move old Entity Displays wheels out of the active scan directory too. Put
   just the new wheel in `plugins`.
5. Start normally, verify one registration, accept the RP and check `/ed list`.

Do not install globally with an unrelated Python interpreter and assume Endstone
will find it. Do not run wheel and direct installations against the same live
installation at the same time.

### Direct source installation (alternative)

From the source project, use PowerShell:

```powershell
./install.ps1 -StageUpdate
# Or target another server directory:
./install.ps1 -Server 'C:/Servers/Bedrock' -StageUpdate
```

This backs up owned package files and loader metadata to
`plugins/entity_displays/install-backups/<unique-id>/`. It migrates this
project's `0.1.0`/`0.2.0`/`0.2.1` direct registrations to `0.2.2`, retaining old metadata
outside discovery. It never stops/restarts the server, reloads plugins or edits
live world pack lists. Restart afterward. This is an alternative to wheel
installation, not an additional step after it.

### Disabling or uninstalling

Stop the server and follow your host's uninstall process for the installed
distribution as well as removing the active wheel. Removing a wheel alone can
leave a registered Python entry point. Keep the data folder for later recovery.
Client-only displays do not become blocks; clients recreate them only while
the plugin runs.

If removing owned packs, back up first and remove only their two UUID entries
and matching folders. Legacy real `ed:oak_planks` world entities may still need
the pack. Leaving the owned packs installed does not delete any saved records.

## Quick start

Look into a clear area and run these one at a time:

```text
/ed create minecraft:stone
/ed info
/ed size 2 3 0.25
/ed rotate 0 45 0
/ed offset 0 1 0
/ed clone
```

Creation selects the new display; cloning selects the copy. To delete that copy
without aiming, take its ID from `/ed info` and use `/ed remove <id>`.
`/ed remove` without an ID instead deletes the nearest aimed display, not
necessarily the selected one.

Try special models and the demo separately:

```text
/ed create minecraft:chest
/ed create minecraft:oak_door
/ed spider
/ed spider remove
```

## Commands and permissions

All commands are in-game only; console use is refused. `/entitydisplay` is an
alias for `/ed` with the same arguments.

| Command | Behavior |
| --- | --- |
| `/ed` | Create/select an oak-plank display. |
| `/ed create` | Same default oak-plank creation. |
| `/ed create <namespace:block>` | Resolve a registered block, create it where you look, then select it. |
| `/ed help` | Show short in-game command help. |
| `/ed select` | Select the nearest aimed display within 6 blocks. |
| `/ed select <id>` | Select by full ID or unambiguous prefix of at least 8 characters. |
| `/ed list` | Count and first 20 displays in your current dimension. |
| `/ed info` | Selected ID, block, position, size, rotation and mode. |
| `/ed move <x> <y> <z>` | Absolute world position, using the bottom-centre anchor. |
| `/ed offset <dx> <dy> <dz>` | Add a position offset. |
| `/ed size <width> <height> <depth>` | Set visual dimensions in blocks. |
| `/ed scale <factor>` | Multiply all three current dimensions. |
| `/ed rotate <x> <y> <z>` | Set absolute XYZ model angles in degrees, not additive rotation. |
| `/ed block <namespace:block>` | Change the selected block appearance. |
| `/ed mode auto` | Choose a supported special model, otherwise native/cuboid as appropriate. |
| `/ed mode native` | Original default-state falling-block visual; unit size/zero rotation only, refused for supported special models. |
| `/ed mode cuboid` | Explicitly use a transformable six-face textured box. |
| `/ed mode model` | Supported door/chest mesh; other blocks are refused. |
| `/ed clone` | Copy at +1 block on X and select the new copy. |
| `/ed remove` | Delete nearest aimed display within 6 blocks, respecting world obstructions. |
| `/ed remove <id>` | Delete a specific ID/prefix without an aim requirement. |
| `/ed spider` | Create/replace your temporary 20-part spider. |
| `/ed spider remove` | Remove only your own demo's remaining tracked parts. |

Edits use your selected display. If it no longer exists, the plugin tries your
aimed display and selects it. Selection is per-player and clears on disconnect;
losing selection does not delete a persistent display. Ordinary displays have
no ownership restriction: any authorized admin can edit/remove them.

Permission: `entitydisplays.admin`, default `op`. Use your existing permissions
manager to grant it to others. There are no separate subcommand permissions,
per-display ACLs or public editing mode.

Arguments must be numbers, not `~`, `^` or expressions. `/ed move` does not
change dimension; use code for that. There is no bulk-remove command.

## Placement, selection and transforms

### Placement and picking

Looking at a world block places the display in the adjacent empty voxel reached
by the command raycast. Open-air placement puts its anchor roughly 3 blocks
along the eye ray, with the original half-block vertical offset. Doors extend
upward by their full height. Creation checks visual bounds against occupied
world cells, including a door's upper half, and never replaces/breaks a block.

Subsequent edits validate world limits but do not run terrain collision checks:
deliberate wall overlap is allowed. Displays cannot support players or block a
path. The assembled spider demo does not run normal placement-clearance checks
for every part.

Picking uses the transformed logical bounding box, not the zero-size network
hitbox. A chest uses its enclosing box rather than exact mesh faces; native
stairs/slabs use the unit cube. Aim-based operations stop at non-air world
blocks. Explicit ID operations work remotely.

### Anchor and dimensions

`position = (x, y, z)` is the bottom-centre of the **unrotated** box. Its rotation
centre is `(x, y + height / 2, z)`. Tilting can extend the visual below the
anchor: it is not recomputed to the lowest rotated point.

Width/height/depth must each be finite and within `0.05`–`32` blocks, inclusive,
rounded to `0.001` blocks. `/ed scale 2` turns `2 × 3 × 0.25` into `4 × 6 × 0.5`,
preserving proportions. Zero, negative, infinite and NaN sizes are rejected.

### Rotation and bounds

Angles are normalized around `[-180, 180)` and rounded to `0.001` degrees.
The hierarchy applies roll Z, then pitch X, then yaw Y about the centre.
Custom meshes rotate through RP bone animations, not native actor rotation.
Client orientation still needs an in-game check for asymmetric textures.

| Dimension | API ID | Supported vertical envelope |
| --- | --- | --- |
| Overworld | `0` | `-64` through `320` |
| Nether | `1` | `0` through `128` |
| End | `2` | `0` through `256` |

The entire rotated box must fit that envelope and the horizontal limit of
`29,999,980` on each axis. Custom dimensions are unsupported. A two-block door
at Y=319 is rejected even though its anchor alone fits in the Overworld.

## Render modes and block support

| Mode | Visual | Pack requirement | Main limitation |
| --- | --- | --- | --- |
| `native` | `minecraft:falling_block`, using the server's block runtime ID | No ED model RP for ordinary vanilla blocks; custom blocks need their own packs | Unit size/zero rotation; unusual/block-entity renderers may be absent/inaccurate. |
| `cuboid` | `ed:cuboid`, six face textures on a box | Bundled RP | Not the original stairs/slab/fence mesh. |
| `model` | `ed:model`, closed chest or two-half door | Bundled RP | Explicit supported-model catalog only. |
| `auto` | Selection policy, not a stored actor type | Depends on selected mode | Special model first; otherwise cuboid for transforms, otherwise native. |

Ordinary untransformed blocks resolve through `Server.create_block_data`.
There are **1,348 cuboid texture mappings** and **34 special-model entries**,
including both oak-door names. A valid server ID is not a guarantee of a correct
native visual, every transform mode or a dedicated special mesh.

Use lowercase Bedrock block identifiers, such as `minecraft:stone`, not item
IDs, Java-only names, texture paths or state expressions. Unknown/unregistered
blocks and invisible air, cave/void air, structure void and invisible bedrock
are refused. Missing mappings are never silently replaced with oak.

Transforming an ordinary native block chooses cuboid mode. Supported doors and
chests keep their special mesh. Explicit cuboid mode remains a box until a mode
change. Changing a special model to an ordinary block preserves dimensions and
chooses an appropriate non-model mode; it does not silently reset size.

To restore an ordinary native shape:

```text
/ed size 1 1 1
/ed rotate 0 0 0
/ed mode native
```

Custom blocks need their registered add-on and client packs. Native mode uses
that add-on's appearance; transformed custom cuboids also need explicit texture
mappings. The generic cuboid mapper does not reproduce arbitrary block states,
biome tint, connected-neighbour shapes, special animated textures or block data.

## Door and chest models

### Doors

A complete thin door uses separate upper/lower textures. Natural dimensions:
`1 × 2 × 0.188` blocks. Supported entries, prefixed with `minecraft:`:

- `wooden_door` / `oak_door`, spruce, birch, jungle, acacia and dark oak doors;
- iron, crimson, warped, mangrove, bamboo, cherry and pale oak doors;
- poplar door if registered by the installed server;
- copper, exposed/weathered/oxidized copper doors and their waxed counterparts.

The oak-door name falls back to `minecraft:wooden_door` only if the requested
`minecraft:oak_door` name is not itself registered. A mapping alone does not
make a newer/experimental block available on your server.

### Chests

Closed single chests have a body, lid and latch, approximately
`0.875 × 0.875 × 0.938` blocks including the latch. Models cover normal `chest`,
`trapped_chest`, `ender_chest`, four copper oxidation stages, and waxed copper
versions, subject to registration.

These are decorative: no inventories, ender storage, redstone, collision or
opening behavior. Double/connected chests, hinge/open states, opening animations
and interaction handlers are not implemented. An explicit API size overrides
natural size. XYZ transforms keep the mesh. Explicit cuboid mode is available
if a textured box is intentional.

### Existing displays

Saved native doors/chests upgrade in memory at startup, preserving IDs and
bottom-centre positions while applying natural model dimensions. The file is
not rewritten until the next normal save. A replacement that exceeds bounds
is retained unchanged and hidden with a warning, not deleted or moved.

Old explicit cuboids are not upgraded. Select one and use `/ed mode auto`.
If a door still has cube proportions, use `/ed size 1 2 0.188` as well.

## Spider demo

`/ed spider` places a static spider about 4.5 blocks ahead at your feet height,
facing the nearest cardinal direction toward you. Its 20 independent cuboid
records are a body, head, two red eyes and eight two-piece legs. It uses black,
gray and red concrete and requires the bundled RP.

The body becomes selected. Moving it does **not** move the other parts: there
is no scene parenting. Repeating the command builds a new demo before replacing
your old one, preserving the old demo on creation failure. Partial new parts
are rolled back when creation fails.

`/ed spider remove` removes your tracked remaining parts, including individually
edited parts; already removed parts are ignored. Other players' demos and
unrelated records are untouched. Command-created demos also disappear when
their creator leaves and are not restored on restart. There is no AI, attack,
walking animation or extra tick task.

Code can call `endstone_entity_displays.spider.create_spider(api, origin,
dimension=0, yaw=0)`. The returned `SpiderDemo` has `parts` (IDs), `body_id` and
`remove()`. When calling the helper directly, manage cleanup in your own plugin;
per-player disconnect tracking belongs to the `/ed spider` workflow.

## Python API

### Obtain the provider

Distribution: `endstone-entity-displays`; import: `endstone_entity_displays`;
Endstone plugin: `entity_displays`. The public API's `api_version` is `1`.

Declare a dependency and acquire the API after enable:

```python
from endstone.plugin import Plugin


class DisplayExamplePlugin(Plugin):
    api_version = "0.11"
    depend = ["entity_displays"]

    def on_enable(self):
        provider = self.server.plugin_manager.get_plugin("entity_displays")
        if provider is None or not provider.ready:
            raise RuntimeError("Entity Displays must be enabled first.")
        self.displays = provider.api
```

Call only on the server/main thread. Worker calls raise `RuntimeError` before
native access; schedule main-thread work if necessary. API objects become
inactive on provider disable. Reacquire the API and handles after re-enable.

Handles retain only the API and display ID, never a native Player/Actor wrapper.
The API does not enforce player permissions or ownership; consumers must
authorize their own interactions.

### Create and edit

```python
provider = self.server.plugin_manager.get_plugin("entity_displays")
api = provider.api
panel = api.create(
    "minecraft:oak_planks", (10, 70, 10), dimension=0,
    size=(2, 3, 0.25), rotation=(0, 0, 0), mode="auto", persistent=True,
)
panel.width = 2.5
panel.height = 4
panel.depth = 0.5
panel.move_to(15, 70, 10)
panel.translate(0, 1, 0)
panel.rotate(0, 45, 0)
panel.scale(1.5)
panel.set_block("minecraft:stone")
copy = panel.clone(position=(18, 70, 10))
copy.remove()

chest = api.create("minecraft:chest", (12, 70, 10))  # Natural dimensions.
door = api.create("minecraft:oak_door", (14, 70, 10))
door.rotate(0, 90, 0)
```

Dimension must be integer `0`, `1` or `2`, not a Dimension object/name. Position,
size and rotation accept three-element lists/tuples of finite numbers; booleans
are not accepted as coordinates or sizes.

### API methods

| Method | Contract |
| --- | --- |
| `api.create(block, position, *, dimension=0, size=None, rotation=(0,0,0), mode="auto", persistent=True)` | Validate/create and return a handle. `size=None` chooses natural model dimensions or a unit box. Persistent creation saves before delivery. |
| `api.get(id_or_prefix)` | Handle or `None` for a valid but missing ID/prefix. Malformed/short/ambiguous prefixes raise `ValueError`. A handle from the same API is also accepted. |
| `api.list(*, dimension=None)` | Tuple of handles, optionally filtered by dimension ID. |
| `api.update(id_or_handle, *, save=True, **changes)` | Change supported fields together; return a handle. Fields: `block`, `position`, `dimension`, `size`, `rotation`, `mode`, `persistent`. |
| `api.remove(id_or_handle)` | Delete one record/visual. Missing records raise `ValueError`; persistent removal saves first. |
| `api.clone(id_or_handle, **changes)` | Independent copy/new ID, retaining fields unless overridden. Unlike `/ed clone`, no automatic X offset. |
| `api.flush()` | Save current persistent records, including earlier no-save edits; temporary records are omitted. |

### Handle properties and methods

| Member | Behavior |
| --- | --- |
| `handle.id` | Stable full 32-character display ID. |
| `handle.snapshot` | Current immutable `Display` record. |
| `handle.position`, `handle.size` | Current tuples; use methods to change them. |
| `handle.width`, `.height`, `.depth` | Read/write axis dimensions; setters preserve the other axes and perform a saving edit. |
| `handle.move_to(x, y, z, *, dimension=None, save=True)` | Absolute position; optional dimension change. |
| `handle.translate(dx, dy, dz, *, save=True)` | Relative movement. |
| `handle.resize(width, height, depth, *, save=True)` | Absolute dimensions. |
| `handle.scale(amount, *, save=True)` | Positive multiplicative factor across all axes. |
| `handle.rotate(x, y, z, *, save=True)` | Absolute model angles. |
| `handle.set_block(block, *, save=True)` | Change appearance while retaining transform, except natural sizing when an ordinary unit native block becomes a special model. |
| `handle.update(*, save=True, **changes)` | Multi-field edit. |
| `handle.clone(**changes)` | Independent copy; no implicit offset. |
| `handle.remove()` | Remove this display. |

Snapshot fields: `id`, `block`, `dimension`, `position`, `size`, `rotation`,
`mode`, `persistent`. Keep IDs rather than stale snapshots if other code edits
the display:

```python
display_id = panel.id
current = api.get(display_id)
if current is not None:
    current.update(position=(20, 72, 20), size=(3, 2, 0.5), rotation=(0, 30, 0))
```

### Errors and transactions

- Invalid IDs/transforms, unknown fields/mappings, unsupported modes and stale
  handles raise `ValueError`.
- Disabled API and wrong-thread calls raise `RuntimeError`.
- Filesystem errors can propagate `OSError`/related exceptions. A failed saving
  edit leaves the previous in-memory record and saved file unchanged.
- Validation happens before saving/sending. Packet failures are logged/retried;
  they do not undo an already committed record.
- `save` and `persistent` must be actual booleans. No actor accessor, arbitrary
  metadata, interaction callback or scene-parent API is provided.

### Temporary records versus no-save edits

```python
preview = api.create("minecraft:glass", (0, 70, 0), persistent=False)
preview.move_to(1, 70, 0, save=False)
api.flush()  # Preview is still omitted from disk.
preview.remove()
```

`persistent=False` excludes a record from every saved file and restart restore.
It does not assign ownership or a lifetime timeout. The consumer should remove
its temporary displays when no longer needed.

`save=False` skips a disk write for that edit; it does not make a persistent
display temporary. Another saving operation or `flush()` can commit its current
pose. Provider disable does not implicitly flush unsaved animation frames.

## Animation and multi-part scenes

Use `save=False` for frequent movement/rotation and flush once at the final
persistent pose. Avoid saving property setters such as `handle.height` every
frame; use `resize(..., save=False)` instead.

Visible clients receive move/property packets with the same fake actor ID while
the render type stays unchanged. Switching mode/type needs one remove/add.
New nearby viewers see the latest snapshot at the next poll. Movement is
immediate; Java interpolation duration/client smoothing is not implemented.

Example inside a consumer plugin method:

```python
provider = self.server.plugin_manager.get_plugin("entity_displays")
api = provider.api
display = api.create("minecraft:stone", (10, 70, 10), mode="cuboid")
state = {"tick": 0, "task": None}


def frame():
    try:
        if api.get(display.id) is None:
            state["task"].cancel()
            return
        state["tick"] += 1
        progress = state["tick"] / 100
        display.update(position=(10 + progress * 5, 70, 10),
                       rotation=(0, progress * 90, 0), save=False)
        if state["tick"] >= 100:
            state["task"].cancel()
            api.flush()
    except (RuntimeError, ValueError):
        state["task"].cancel()


state["task"] = self.server.scheduler.run_task(self, frame, delay=1, period=1)
```

Keep/cancel the task in your consumer's `on_disable`; handle/log final flush
filesystem errors according to your recovery policy. This five-second example
uses caller-driven per-tick updates, not a built-in ED animation loop. Another
finite example is in source `examples/display_api_example.py`.

Multi-part objects are collections of IDs, not scene graphs. To move all parts,
retain their local offsets and update each through the API. Parent transforms,
child propagation, batch transactions and built-in animation tracks are absent.
Implement partial-build rollback, task cancellation and cleanup in the caller.
Persistent scene-to-part-ID mappings belong in your own plugin's data folder.
Avoid retaining native Player/Actor wrappers across scheduled callbacks.

## Persistence and backups

Persistent records use schema version `2` at
`plugins/entity_displays/displays.json`. Example (illustrative ID):

```json
{
  "version": 2,
  "displays": [
    {
      "id": "0123456789abcdef0123456789abcdef",
      "block": "minecraft:stone",
      "dimension": 0,
      "position": [10, 70, 10],
      "size": [2, 3, 0.25],
      "rotation": [0, 45, 0],
      "mode": "cuboid",
      "persistent": true
    }
  ]
}
```

Writes use an fsynced temporary file and atomic replacement. A failed write
preserves previous active state and disk data. This is not rolling backup
history: make independent data backups before upgrades/restores. Pack-list and
installer backups are separate; do not assume they include the latest records.

Block runtime IDs, fake actor IDs and viewers are not saved. Current block IDs
resolve against the palette after restart. A missing custom add-on hides its
saved visuals with a warning without discarding records. Restore the add-on and
restart to retry those displays.

Version-1 records load without immediate rewriting and receive unit size/zero
rotation/default persistence. The next save writes version 2. Native special
models follow the upgrade rules above. Duplicate IDs/JSON keys, unknown fields,
oversized files and unsupported schemas are refused, not silently discarded.

For restores, stop the server, preserve the current file, restore a known-good
copy and start normally. Do not edit a live file that the next save can replace.

## Performance and limits

| Setting | Built-in value |
| --- | --- |
| Visibility interval | 20 ticks, nominally 1 second |
| Nearby spatial buckets | Nine X/Z buckets/player, 128 blocks wide |
| Show distance | 48 blocks plus visual bounding radius |
| Hide distance | 56 blocks plus visual bounding radius |
| Visible cap | 256 display records/viewer, nearest first |
| Send budget | 32 new/changed display records/viewer/poll |
| Record limit | 10,000 active, including temporary records |
| Size range | 0.05–32 blocks per axis |
| Saved-file load limit | 8 MiB |
| Pack archive uncompressed limit | 2 MiB |

These are code constants, not configuration options. There is currently no
plugin-specific `config.yml`, distance command or refresh command.

Sparse visibility polling runs only while records or pending removals exist,
then stops when empty. No per-tick world/actor scans, ticking areas or AI are
used. Native lookups, shared packet payloads and viewer snapshots are cached.
Static shown records do not resend unchanged visuals. Ordinary join/dimension
delivery allows a short handshake delay; explicit creation may show immediately.

Placement/picking reads blocks at command time. Aim removal scans the dimension
actor list once for legacy oak entities, not in the polling loop. Complex scenes
still cost rendering/network/bookkeeping: 20 spider parts count as 20 records.
No-save animation avoids disk I/O but can still send many packets. Limit scene
size and frame rate in the consumer.

Disconnect, death/respawn, dimension changes, leaving range, removal and disable
clean up/recreate appropriate visuals. Persistent records survive normal
restarts. Original real `ed:oak_planks` prototype entities remain intact and
can still be removed with `/ed remove`.

## Troubleshooting

| Symptom / log | Check and remedy |
| --- | --- |
| Unknown `/ed` command | Check wheel discovery, entry point, startup errors and permissions. Commands are in-game only. |
| Missing permission | Use an operator or grant exact permission `entitydisplays.admin`. |
| Unsupported protocol | Use the target build or properly update/validate the codec; do not suppress the check. |
| Unknown/unavailable block | Use a lowercase registered Bedrock block ID, not an item/Java ID. Install custom add-ons first. |
| Door name not found | Try `minecraft:wooden_door`; oak has a historical-name fallback. |
| No cuboid mapping | Use native mode at unit size/zero rotation, or add a verified mapping and rebuild. |
| No special model | Model mode is for supported doors/chests only; use auto/cuboid for others. |
| Chest/door missing while stone renders | Check pack errors, client pack acceptance/cache, installed RP version and render mode. |
| Door still cube-shaped | Old explicit cuboids do not auto-upgrade. Select, `/ed mode auto`, then `/ed size 1 2 0.188` if needed; accept the new RP. |
| Chest does not open | Expected: decorative entity, not working storage. |
| Resized stairs become a box | Expected: generic transforms use cuboids, not stretched native stair meshes. |
| Not enough clear space | Aim somewhere open; doors need the full two-block height. Later edits can intentionally overlap terrain. |
| Bounds error | Move/resize/rotate to fit the entire box, not just its anchor. |
| Saved record kept but hidden | Fix the missing block/pack/mapping or special-model mode; restart or edit by ID. Data is retained. |
| Special upgrade kept unchanged | Model might exceed bounds or pack is unavailable. Fix startup, move into bounds and select auto mode. |
| Packet sync warning | Delivery retries. Check client/server protocol/connectivity before editing records. |
| Pack ownership/newer-version error | Back up and inspect the owned folder/manifest; do not overwrite unrelated/newer packs. |
| Storage failed to load | Preserve the file, inspect the error, restore a known-good backup while stopped. |
| Cannot aim at display | Move within 6 blocks, clear obstructions or select/remove by ID. |
| Wrong display edited | Check `/ed info` and select explicitly. Removal without ID is aim-based. |
| Spider idle / only body moves | Expected: static demo with independent parts; whole-scene motion needs code. |
| Missing distant/crowded displays | Check range, 256-record viewer cap and 32-record poll budget. |
| Wrong-thread API error | Schedule the calls on the server/main thread. |
| Disabled API error | Cancel consumer tasks and acquire a fresh API after re-enable. |
| Duplicate plugin/command loads | Check for direct registrations plus scanned wheels or several metadata versions; migrate while stopped. |

## Building and validating releases

### Source layout

```text
entity-displays/
  pyproject.toml
  README.md
  install.ps1
  src/endstone_entity_displays/       Runtime and embedded assets
  behavior_pack/                    Owned BP sources
  resource_pack/                    Owned RP sources
  tools/                            Generators/validators
  tools/data/terrain_texture.json   Cached Mojang mapping
  tests/test_displays.py             Offline tests
  examples/display_api_example.py   Consumer examples, not auto-executed
  dist/                             Built wheels
```

### Build the wheel

Run in this project directory. PEP 517 uses Hatchling from the project's build
requirements; pip may fetch build tools. This builds files, not a live server
installation:

```powershell
python -B tools/build_packs.py
python -m pip wheel --no-deps --no-cache-dir --wheel-dir dist .
python -B tools/verify_wheel.py dist/endstone_entity_displays-0.2.2-py3-none-any.whl
```

The wheel includes `assets/display_packs.zip`, `assets/pack_index.json`, and the
README at `endstone_entity_displays/docs/README.md` as well as its `METADATA`
long description. Runtime modules are shipped, not tests, server data, source
examples or the direct installer. Rebuild assets after pack JSON edits.

The verifier needs Python 3.11+ for standard-library TOML parsing. It checks
paths, metadata, entry point, RECORD hashes, pack hashes and source/docs
consistency. It then installs with `--no-deps --no-index` into its own temporary
fixture and imports in a fresh interpreter. Use a development interpreter with
Endstone installed for that native import check; it starts no server and touches
no world files.

### Regenerate texture mappings and special models

The cuboid generator reads installed vanilla `blocks.json` overlays plus the
cached Mojang terrain map. The model generator uses cached door mappings and
the supported chest atlas paths. Both emit JSON, not PNGs.

```powershell
python -B tools/build_cuboids.py --server '../bedrock_server'
python -B tools/build_models.py
python -B tools/build_packs.py
```

`build_cuboids.py --refresh` fetches the official Mojang terrain map; ordinary
builds use the cache. Review new mappings against your target server. For pack
updates, bump manifest/module versions, BP's RP dependency version,
`packs.VERSION` and the build index version together. Bump the project/release
version and installer/version references when publishing another release.

Custom cuboid mappings go in `tools/cuboid_overrides.json`, for example:

```json
{
  "yourpack:marble": "textures/blocks/your_marble",
  "yourpack:panel": {
    "north": "textures/blocks/your_panel_front",
    "south": "textures/blocks/your_panel_back",
    "east": "textures/blocks/your_panel_side",
    "west": "textures/blocks/your_panel_side",
    "up": "textures/blocks/your_panel_top",
    "down": "textures/blocks/your_panel_bottom"
  }
}
```

Provide all six keys or one path for every face. Paths omit `.png` and reference
assets in your installed custom RP. This neither registers a block nor bundles
that RP. Rebuild cuboids/models/bundle and reinstall/restart after mapping edits.

### Validation

```powershell
python -B -m unittest discover -s tests -q
python -B tools/validate_native.py
./tools/validate_install.ps1
python -B tools/verify_wheel.py dist/endstone_entity_displays-0.2.2-py3-none-any.whl
```

There are 127 logic tests in this release. The native validator checks real
command/permission construction, four event annotation types, packet APIs and
references across all 18 pack files. Installer tests use GUID-named isolated
fixtures for fresh/older-version migrations, not the real server. On Windows,
the installer's read-only server-process check needs CIM access.

### In-game release smoke test

1. Start the supported server, accept the RP and check logs.
2. Create stone, grass, logs, glass, stairs and a slab; inspect shapes/textures.
3. Resize/rotate/move a cuboid; walk through it and verify targeting/world safety.
4. Create oak/spruce/iron doors and normal/trapped/ender chests; inspect both
   halves, species textures, body/lid/latch and transformed appearances.
5. Create/replace/remove a spider and test disconnect cleanup.
6. Reconnect/restart, die/respawn, leave range, change dimension and return;
   persistent records should return without duplicates.
7. Remove by aim and ID; verify a wall obstructs aim-based removal.
8. For custom blocks, install/accept their own defining packs first.

Offline tests do not establish final client graphics correctness.

## Known limitations

- Protocols 2193 and 2225 only; no cross-version client translation.
- Decorative blocks only: no inventories, interactions, redstone, fluids, drops,
  collision, AI or world block simulation.
- A registered block does not guarantee a working native model. Unsupported
  special renderers such as signs/beds need further implementation.
- Ordinary transformed blocks become boxes; native non-cube shapes are not
  generally preserved. Explicit door/chest models are exceptions.
- No arbitrary block states, NBT/block data, hinge/open state, double chest
  connections, sign text or biome tint support.
- No item/text-display API, per-player visibility control, interaction callbacks,
  scene parenting, batch transactions or interpolation-duration API.
- No custom dimensions, GUI editor, configuration file or console editing.
- Picking uses logical bounds rather than exact mesh/alpha tests.
- Unsaved persistent animation poses can be lost without a saving operation;
  temporary records are never restored.
- A pure-Python wheel does not eliminate Bedrock/client compatibility limits.

## Release notes

### 0.2.1

Dedicated door/chest meshes; both door halves/species textures; chest
body/lid/latch; natural dimensions; oak-door fallback; door clearance checks;
saved native model upgrades; per-entity-type property schemas; pack 0.2.1.
The wheel embeds the auto-installed BP/RP and extensive README.

### 0.2.0

Main-thread public API; XYZ dimensions/rotation; live move/property packets;
selection/edit/clone commands; temporary/no-save edits; cuboid pack and static
20-part spider demo.

### 0.1.x

Oak-plank prototype and native display foundation. Legacy real oak displays
remain compatible with aim-based removal.

## Technical references

Upstream branches can move; use this release's target protocol, not an
assumption that their latest wire formats are compatible:

- [Endstone Python block API](https://endstone.dev/v0.11/reference/python/block/)
- [Endstone actor packet definitions](https://github.com/EndstoneMC/bedrock-protocol/blob/main/protocol/actor.py)
- [Mojang protocol documentation](https://github.com/Mojang/bedrock-protocol-docs)
- [Mojang sample resources](https://github.com/Mojang/bedrock-samples/tree/main/resource_pack)
- [PocketMine-MP falling-block reference](https://github.com/pmmp/PocketMine-MP/blob/stable/src/entity/object/FallingBlock.php)
