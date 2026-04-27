from dataclasses import dataclass

from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .constants import BOUNDARY_TOUCH_AREA_TOLERANCE
from .models.enumirations import OverlapCase


@dataclass(frozen=True, slots=True)
class OverlapClassification:
    """Результат классификации пересечения пары полигонов."""

    case: OverlapCase
    shared_boundary_vertices: tuple[Point, Point] | None = None


def point_on_boundary(polygon: Polygon, point: Point, tolerance: float = 1e-9) -> bool:
    return polygon.boundary.buffer(tolerance).covers(point)


def _collect_polygon_components(geometry: BaseGeometry) -> list[Polygon]:
    polygons: list[Polygon] = []

    if geometry.is_empty:
        return polygons

    if geometry.geom_type == "Polygon":
        polygons.append(geometry)
        return polygons

    if geometry.geom_type == "MultiPolygon":
        for polygon in geometry.geoms:
            polygons.append(polygon)
        return polygons

    if geometry.geom_type == "GeometryCollection":
        for part in geometry.geoms:
            polygons.extend(_collect_polygon_components(part))
        return polygons

    return polygons


def find_significant_overlaps(first_polygon: Polygon, second_polygon: Polygon) -> list[Polygon]:
    intersection_geometry = first_polygon.intersection(second_polygon)
    overlap_polygons = _collect_polygon_components(intersection_geometry)

    significant_overlaps = []

    for polygon in overlap_polygons:
        if polygon.area > BOUNDARY_TOUCH_AREA_TOLERANCE:
            significant_overlaps.append(polygon)

    return significant_overlaps


def classify_overlap_vertices(
    overlap_polygon: Polygon,
    first_polygon: Polygon,
    second_polygon: Polygon,
    tolerance: float = 1e-9,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

    for coord_x, coord_y in overlap_polygon.exterior.coords[:-1]:
        point = Point(coord_x, coord_y)

        on_first_boundary = point_on_boundary(first_polygon, point, tolerance)
        on_second_boundary = point_on_boundary(second_polygon, point, tolerance)

        result.append(
            {
                "point": (coord_x, coord_y),
                "on_first_boundary": on_first_boundary,
                "on_second_boundary": on_second_boundary,
                "inside_first": not on_first_boundary,
                "inside_second": not on_second_boundary,
            }
        )

    return result


def classify_significant_overlaps(
    significant_overlaps: list[Polygon],
    first_polygon: Polygon,
    second_polygon: Polygon,
) -> OverlapClassification:
    if not significant_overlaps:
        return OverlapClassification(case=OverlapCase.no_overlap)

    for overlap_polygon in significant_overlaps:
        vertex_info = classify_overlap_vertices(
            overlap_polygon=overlap_polygon,
            first_polygon=first_polygon,
            second_polygon=second_polygon,
        )

        shared_boundary_vertex_count = 0
        inside_vertex_count = 0
        shared_boundary_vertices: list[Point] = []

        for item in vertex_info:
            on_first_boundary = item["on_first_boundary"]
            on_second_boundary = item["on_second_boundary"]
            point = item["point"]

            if on_first_boundary and on_second_boundary:
                shared_boundary_vertex_count += 1
                coord_x, coord_y = point
                shared_boundary_vertices.append(Point(coord_x, coord_y))
            else:
                inside_vertex_count += 1

        # Вложенность
        if shared_boundary_vertex_count == 0:
            return OverlapClassification(case=OverlapCase.all_points_inside_one_polygon)

        # Треугольный оверлап (3 вершины, 2 общие, 1 внутренняя)
        if len(vertex_info) == 3 and shared_boundary_vertex_count == 2 and inside_vertex_count == 1:
            return OverlapClassification(
                case=OverlapCase.candidate_block_4,
                shared_boundary_vertices=(shared_boundary_vertices[0], shared_boundary_vertices[1]),
            )

        # Четырёхугольный оверлап (4 вершины, 2 общие, 2 внутренние) – например, два квадрата
        if len(vertex_info) == 4 and shared_boundary_vertex_count == 2 and inside_vertex_count == 2:
            # Дополнительная проверка: нет общего отрезка границы
            boundary_cross = first_polygon.boundary.intersection(second_polygon.boundary)
            has_linear = any(
                g.geom_type in ("LineString", "MultiLineString")
                for g in (boundary_cross.geoms if hasattr(boundary_cross, "geoms") else [boundary_cross])
            )
            if not has_linear:
                return OverlapClassification(
                    case=OverlapCase.candidate_block_4,
                    shared_boundary_vertices=(shared_boundary_vertices[0], shared_boundary_vertices[1]),
                )

        # Все остальные случаи (больше 4 вершин, больше 2 общих вершин, общий отрезок) → блок 5
        if len(vertex_info) > 3 or shared_boundary_vertex_count > 2:
            return OverlapClassification(case=OverlapCase.candidate_block_5)

    return OverlapClassification(case=OverlapCase.unsupported)


def _classify_pair(first_polygon: Polygon, second_polygon: Polygon) -> OverlapClassification:
    """Классифицирует пересечение пары полигонов по площади и вершинам оверлапа."""
    significant_overlaps = find_significant_overlaps(first_polygon, second_polygon)
    return classify_significant_overlaps(
        significant_overlaps=significant_overlaps,
        first_polygon=first_polygon,
        second_polygon=second_polygon,
    )
