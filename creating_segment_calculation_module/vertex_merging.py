from shapely.geometry import Polygon

from .constants import CALCULATION_NAME


def _collect_polygon_vertices(polygons: list[Polygon]) -> list[tuple[int, int, float, float]]:
    """Собирает все вершины полигонов без замыкающей точки."""
    vertices: list[tuple[int, int, float, float]] = []

    for polygon_index, polygon in enumerate(polygons):
        coords = list(polygon.exterior.coords)
        for vertex_index, (coord_x, coord_y) in enumerate(coords[:-1]):
            vertices.append((polygon_index, vertex_index, coord_x, coord_y))

    return vertices


def _find_neighbor_vertices(
    vertices: list[tuple[int, int, float, float]],
    base_polygon_index: int,
    base_x: float,
    base_y: float,
    radius_squared: float,
) -> tuple[list[tuple[int, int, float, float]], dict[int, int]]:
    """Находит соседние вершины из других полигонов в пределах радиуса."""
    neighbors: list[tuple[int, int, float, float]] = []
    neighbor_counts: dict[int, int] = {}

    for candidate_polygon_index, candidate_vertex_index, candidate_x, candidate_y in vertices:
        if candidate_polygon_index == base_polygon_index:
            continue

        delta_x = candidate_x - base_x
        delta_y = candidate_y - base_y
        if (delta_x * delta_x + delta_y * delta_y) > radius_squared:
            continue

        neighbors.append((candidate_polygon_index, candidate_vertex_index, candidate_x, candidate_y))
        current_count = neighbor_counts.get(candidate_polygon_index, 0)
        neighbor_counts[candidate_polygon_index] = current_count + 1

    return neighbors, neighbor_counts


def _build_merge_group(
    base_polygon_index: int,
    base_vertex_index: int,
    base_x: float,
    base_y: float,
    neighbors: list[tuple[int, int, float, float]],
) -> tuple[list[tuple[int, int, float, float]], float, float]:
    """Строит группу склейки и считает среднюю точку."""
    group = [(base_polygon_index, base_vertex_index, base_x, base_y), *neighbors]
    avg_x = sum(item[2] for item in group) / len(group)
    avg_y = sum(item[3] for item in group) / len(group)

    return group, avg_x, avg_y


def _collect_polygon_moves(
    polygon_index: int,
    planned_moves: dict[tuple[int, int], tuple[float, float]],
) -> dict[int, tuple[float, float]]:
    """Собирает все сдвиги, относящиеся к одному полигону."""
    polygon_moves: dict[int, tuple[float, float]] = {}

    for (poly_idx, vertex_index), point in planned_moves.items():
        if poly_idx == polygon_index:
            polygon_moves[vertex_index] = point

    return polygon_moves


def _register_planned_moves(
    group: list[tuple[int, int, float, float]],
    avg_x: float,
    avg_y: float,
    planned_moves: dict[tuple[int, int], tuple[float, float]],
) -> None:
    """Регистрирует запланированные сдвиги для группы."""
    for polygon_index, vertex_index, vertex_x, vertex_y in group:
        vertex_key = (polygon_index, vertex_index)
        if vertex_key not in planned_moves:
            planned_moves[vertex_key] = (avg_x, avg_y)


def _apply_polygon_moves(
    polygon_index: int,
    polygon: Polygon,
    polygon_moves: dict[int, tuple[float, float]],
) -> Polygon:
    """Применяет сдвиги к одному полигону."""
    original_coords = list(polygon.exterior.coords)
    updated_coords = list(original_coords)

    for vertex_index, new_point in polygon_moves.items():
        updated_coords[vertex_index] = new_point

    if 0 in polygon_moves:
        updated_coords[-1] = updated_coords[0]

    return Polygon(updated_coords)


def merge_by_radius(
    polygons: list[Polygon],
    merge_radius: float,
    polygon_name: str,
) -> tuple[list[Polygon], list[str], list[str]]:
    """Склеивает близкие вершины разных полилиний в пределах заданного радиуса."""
    warnings: list[str] = []
    infos: list[str] = []

    if merge_radius <= 0 or len(polygons) < 2:
        return polygons, warnings, infos

    vertices = _collect_polygon_vertices(polygons)
    planned_moves: dict[tuple[int, int], tuple[float, float]] = {}
    has_skip_info = False
    radius_squared = merge_radius * merge_radius

    for base_polygon_index, base_vertex_index, base_x, base_y in vertices:
        neighbors, neighbor_counts = _find_neighbor_vertices(
            vertices,
            base_polygon_index,
            base_x,
            base_y,
            radius_squared,
        )

        if not neighbors:
            continue

        if any(hit_count > 1 for hit_count in neighbor_counts.values()):
            has_skip_info = True
            continue

        group, avg_x, avg_y = _build_merge_group(
            base_polygon_index,
            base_vertex_index,
            base_x,
            base_y,
            neighbors,
        )
        _register_planned_moves(group, avg_x, avg_y, planned_moves)

    if has_skip_info:
        infos.append(
            f'{CALCULATION_NAME}'
            f'Для некоторых полилиний полигона {polygon_name} в радиус склейки входит более 1 точки одной полилинии. '
            f'Склейка не будет выполнена.',
        )

    if not planned_moves:
        return polygons, warnings, infos

    result_polygons: list[Polygon] = []
    for polygon_index, polygon in enumerate(polygons):
        polygon_moves = _collect_polygon_moves(polygon_index, planned_moves)

        if not polygon_moves:
            result_polygons.append(polygon)
            continue

        updated_polygon = _apply_polygon_moves(
            polygon_index,
            polygon,
            polygon_moves,
        )

        if not updated_polygon.is_valid or not updated_polygon.is_simple:
            warnings.append(
                f'{CALCULATION_NAME}'
                f'Полилиния полигона {polygon_name} исключена из расчёта из-за самопересечения после склейки.',
            )
            continue

        result_polygons.append(updated_polygon)

    return result_polygons, warnings, infos
