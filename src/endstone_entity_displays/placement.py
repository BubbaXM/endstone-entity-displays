"""Small command-time voxel raycast and visual cube picking; no native objects."""
import math

AIR = frozenset({"minecraft:air", "minecraft:cave_air", "minecraft:void_air"})
REACH = 6.0


def view_ray(location, sneaking=False):
    yaw, pitch = math.radians(location.yaw), math.radians(location.pitch)
    return ((location.x, location.y + (1.27 if sneaking else 1.62), location.z),
            (-math.sin(yaw) * math.cos(pitch), -math.sin(pitch), math.cos(yaw) * math.cos(pitch)))


def voxels(origin, direction, reach=REACH):
    if not all(math.isfinite(value) for value in (*origin, *direction, reach)) or not 0 <= reach <= 64:
        raise ValueError("Invalid display ray.")
    length = math.sqrt(sum(value * value for value in direction))
    if length < 1e-9:
        raise ValueError("Display ray needs a direction.")
    direction = tuple(value / length for value in direction)
    cell = [math.floor(value) for value in origin]
    step = [1 if value > 0 else -1 for value in direction]
    delta = [abs(1 / value) if abs(value) > 1e-12 else math.inf for value in direction]
    edge = [((cell[i] + 1 - origin[i]) if step[i] > 0 else (origin[i] - cell[i])) * delta[i]
            if math.isfinite(delta[i]) else math.inf for i in range(3)]
    distance = 0.0
    while distance <= reach:
        yield tuple(cell), distance
        axis = min(range(3), key=edge.__getitem__)
        distance = edge[axis]
        cell[axis] += step[axis]
        edge[axis] += delta[axis]


def first_block(origin, direction, block_at):
    previous = None
    for cell, distance in voxels(origin, direction):
        if block_at(*cell) not in AIR:
            return cell, previous, distance
        previous = cell
    return None


def spawn_position(origin, direction, block_at, size=(1, 1, 1)):
    hit = first_block(origin, direction, block_at)
    if hit:
        _, adjacent, _ = hit
        if adjacent is None:
            raise ValueError("Move out of the block before creating a display.")
        position = (adjacent[0] + .5, float(adjacent[1]), adjacent[2] + .5)
    else:
        position = (origin[0] + direction[0] * 3, origin[1] + direction[1] * 3 - .5,
                    origin[2] + direction[2] * 3)
    # Creation uses natural model bounds, including the upper door half.
    width, height, depth = size
    for x in range(math.floor(position[0] - width / 2 + 1e-6), math.floor(position[0] + width / 2 - 1e-6) + 1):
        for y in range(math.floor(position[1] + 1e-6), math.floor(position[1] + height - 1e-6) + 1):
            for z in range(math.floor(position[2] - depth / 2 + 1e-6), math.floor(position[2] + depth / 2 - 1e-6) + 1):
                if block_at(x, y, z) not in AIR:
                    raise ValueError("Not enough clear space for the block display. Aim somewhere open.")
    return position


def cube_distance(origin, direction, position):
    lower = (position[0] - .5, position[1], position[2] - .5)
    upper = (position[0] + .5, position[1] + 1, position[2] + .5)
    near, far = 0.0, REACH
    for i in range(3):
        if abs(direction[i]) < 1e-12:
            if not lower[i] <= origin[i] <= upper[i]:
                return None
        else:
            first, last = sorted(((lower[i] - origin[i]) / direction[i], (upper[i] - origin[i]) / direction[i]))
            near, far = max(near, first), min(far, last)
            if near > far:
                return None
    return near
