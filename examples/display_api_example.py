"""Call these helpers from another Endstone plugin on the server thread.

Declare depend = ["entity_displays"] in that plugin so this API is ready.
This example is NOT installed/executed automatically and never retains a Player.
"""
import math


def create_display(server, x, y, z, dimension=0):
    plugin = server.plugin_manager.get_plugin("entity_displays")
    if plugin is None or not plugin.ready:
        raise RuntimeError("Enable Entity Displays first.")
    api = plugin.api
    display = api.create("minecraft:oak_planks", (x, y, z), dimension=dimension,
                         size=(2, 3, .25), mode="cuboid")
    display.height = 4
    display.width = 2.5
    display.move_to(x + 1, y, z)
    display.rotate(0, 45, 0)
    # Also: display.set_block("minecraft:stone"), display.clone(...), display.remove().
    # Stable IDs can be kept and looked up after restart:
    assert api.get(display.id).id == display.id
    return display


def animate_orbit(server, owner_plugin, display, duration_ticks=100):
    """A finite five-second example using immediate updates and NO per-frame disk I/O.

    Moves only this display. No ticking areas, scans, forms or real actors.
    At completion the final persistent pose is saved once. Removing the display
    during the animation cancels it safely. Cancel the task in owner on_disable.
    """
    if type(duration_ticks) is not int or not 1 <= duration_ticks <= 1200:
        raise ValueError("duration_ticks must be between 1 and 1200.")
    start = display.position
    api = server.plugin_manager.get_plugin("entity_displays").api
    progress = {"tick": 0, "task": None}

    def frame():
        try:
            if api.get(display.id) is None:
                progress["task"].cancel()
                return
            progress["tick"] += 1
            angle = progress["tick"] / duration_ticks * math.tau
            display.move_to(start[0] + math.sin(angle), start[1], start[2] + 1 - math.cos(angle), save=False)
            if progress["tick"] >= duration_ticks:
                progress["task"].cancel()
                api.flush()
        except (RuntimeError, ValueError):
            progress["task"].cancel()

    progress["task"] = server.scheduler.run_task(owner_plugin, frame, delay=1, period=1)
    return progress["task"]
