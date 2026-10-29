"""Model-space cuboid transforms shared by validation and ray picking.

Anchor is bottom-centre of the unrotated box; rotation is XYZ degrees, applied
roll Z, then pitch X, then yaw Y (matching the generated bone hierarchy).
"""
import math

MIN_SIZE, MAX_SIZE = .05, 32.0


def vector(value, label):
    if not isinstance(value, (tuple, list)) or len(value) != 3 or not all(
            type(v) in (int, float) and math.isfinite(v) for v in value):
        raise ValueError(f"{label} must contain three finite numbers.")
    return tuple(float(v) for v in value)


def size_vector(value):
    result = vector(value, "Size")
    if any(not MIN_SIZE <= v <= MAX_SIZE for v in result):
        raise ValueError(f"Each visual size must be between {MIN_SIZE} and {MAX_SIZE} blocks.")
    return tuple(round(v, 3) for v in result)


def rotation_vector(value):
    return tuple(round((v + 180) % 360 - 180, 3) for v in vector(value, "Rotation"))


def transform(point, rotation, inverse=False):
    x, y, z = point
    rx, ry, rz = (math.radians(a) for a in rotation)
    # Explicit axes keep picking consistent with yaw/pitch/roll parent bones.
    def axis_x(p, angle):
        x, y, z = p
        c, s = math.cos(angle), math.sin(angle)
        return x, c * y - s * z, s * y + c * z
    def axis_y(p, angle):
        x, y, z = p
        c, s = math.cos(angle), math.sin(angle)
        return c * x + s * z, y, -s * x + c * z
    def axis_z(p, angle):
        x, y, z = p
        c, s = math.cos(angle), math.sin(angle)
        return c * x - s * y, s * x + c * y, z
    if inverse:
        return axis_z(axis_x(axis_y((x, y, z), -ry), -rx), -rz)
    return axis_y(axis_x(axis_z((x, y, z), rz), rx), ry)


def centre(position, size):
    return position[0], position[1] + size[1] / 2, position[2]


def half_extents(size, rotation):
    axes = [transform(tuple(size[i] / 2 if i == j else 0 for i in range(3)), rotation) for j in range(3)]
    return tuple(sum(abs(axis[i]) for axis in axes) for i in range(3))


def ray_distance(origin, direction, position, size=(1, 1, 1), rotation=(0, 0, 0), reach=6):
    center = centre(position, size)
    local = transform(tuple(origin[i] - center[i] for i in range(3)), rotation, inverse=True)
    view = transform(direction, rotation, inverse=True)
    near, far = 0.0, reach
    for i in range(3):
        radius = size[i] / 2
        if abs(view[i]) < 1e-12:
            if not -radius <= local[i] <= radius:
                return None
        else:
            a, b = sorted(((-radius - local[i]) / view[i], (radius - local[i]) / view[i]))
            near, far = max(near, a), min(far, b)
            if near > far:
                return None
    return near
