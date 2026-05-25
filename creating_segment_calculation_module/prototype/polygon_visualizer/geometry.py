import math


def compute_bounds(layers) -> tuple[float, float, float, float]:
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for layer in layers:
        for poly in layer.polygons:
            bx0, by0, bx1, by1 = poly.bounds
            min_x = min(min_x, bx0)
            min_y = min(min_y, by0)
            max_x = max(max_x, bx1)
            max_y = max(max_y, by1)
    if min_x == float("inf"):
        return 0, 0, 100, 100
    return min_x, min_y, max_x, max_y


def compute_grid_step(view_width: float, view_height: float, target_lines: int = 12) -> float:
    raw_step = max(view_width, view_height) / target_lines
    power = math.floor(math.log10(raw_step))
    base = 10 ** power
    ratio = raw_step / base

    if ratio > 5:
        return 10 * base
    if ratio > 2:
        return 5 * base
    if ratio > 1:
        return 2 * base
    return base


def compute_grid_y_lines(view_y, view_h, flip_offset, step) -> list[tuple[float, float]]:
    math_y_min = flip_offset - (view_y + view_h)
    math_y_max = flip_offset - view_y
    y_start = math.floor(math_y_min / step) * step
    y_end = math.ceil(math_y_max / step) * step

    lines: list[tuple[float, float]] = []
    count = round((y_end - y_start) / step)
    for idx in range(count + 1):
        math_y = y_start + idx * step
        lines.append((math_y, flip_offset - math_y))
    return lines
