"""Small static ED demo: twenty textured boxes, no mob, AI or animation loop.

The two-segment legs are deliberately blocky/axis-aligned so this first demo
tests actual visual sizing without depending on arbitrary-angle calibration.
"""
from dataclasses import dataclass
import math

from .transforms import transform, vector


@dataclass(frozen=True)
class SpiderPart:
    name: str
    block: str
    position: tuple
    size: tuple
    rotation: tuple


def spider_layout(origin, yaw=0):
    origin = vector(origin, "Spider origin")
    if type(yaw) not in (int, float) or not math.isfinite(yaw):
        raise ValueError("Spider yaw must be finite.")
    # Face the nearest cardinal direction; a concrete cuboid at +/-90 degrees
    # has identical shape, so no UV/front-face ambiguity affects this test.
    yaw = (round(yaw / 90) * 90 + 180) % 360 - 180
    parts = []

    def box(name, block, center, size):
        offset = transform(center, (0, yaw, 0))
        center = tuple(origin[i] + offset[i] for i in range(3))
        position = (center[0], center[1] - size[1] / 2, center[2])
        parts.append(SpiderPart(name, block, position, size, (0, yaw, 0)))

    box("body", "minecraft:black_concrete", (0, .95, .35), (1.2, .65, 1.45))
    box("head", "minecraft:gray_concrete", (0, .9, -.75), (.85, .6, .75))
    for side, x in (("left", -.22), ("right", .22)):
        box(f"eye_{side}", "minecraft:red_concrete", (x, 1.0, -1.1525), (.16, .16, .055))
    for side, sign in (("left", -1), ("right", 1)):
        for index, z in enumerate((-.28, .12, .52, .92)):
            # Horizontal upper leg from body edge to the outer knee.
            box(f"leg_{side}_{index}_upper", "minecraft:black_concrete",
                (sign * 1.1, .8, z), (1.25, .13, .13))
            # Vertical lower leg touches the upper leg and ends above the floor.
            box(f"leg_{side}_{index}_lower", "minecraft:black_concrete",
                (sign * 1.66, .44, z), (.13, .72, .13))
    return tuple(parts)


@dataclass(frozen=True)
class SpiderDemo:
    api: object
    parts: tuple
    body_id: str

    def remove(self):
        """Remove only this demo's still-existing parts; safe after manual edits."""
        count = 0
        for identity in self.parts:
            handle = self.api.get(identity)
            if handle is not None:
                handle.remove()
                count += 1
        return count


def create_spider(api, origin, *, dimension=0, yaw=0):
    """Build exclusively through the public ED API; all parts are temporary.

    Roll back any partial creation on error. No private renderer/store calls,
    world-block changes, native entities, timers, forms or disk writes.
    """
    parts = []
    try:
        for part in spider_layout(origin, yaw):
            handle = api.create(part.block, part.position, dimension=dimension,
                                size=part.size, rotation=part.rotation,
                                mode="cuboid", persistent=False)
            parts.append(handle.id)
    except Exception:
        for identity in reversed(parts):
            handle = api.get(identity)
            if handle is not None:
                handle.remove()
        raise
    return SpiderDemo(api, tuple(parts), parts[0])
