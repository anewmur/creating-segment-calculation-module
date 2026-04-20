import json
import logging
from dataclasses import dataclass
from shapely.geometry import LineString
from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from .models.enumirations import (
    ContainmentHandlingResult, ContainmentHandlingStatus, OverlapCase
)
from .models.creating_segments import SEGMENT_TYPE_NAME_ENUM
from .models.creating_segments import CalculationInput
from .models.creating_segments import CalculationResult
from .models.creating_segments import FormationResult
from .models.creating_segment import File
from .models.creating_segments import Line
from .models.creating_segments import PolygonLine
from .models.creating_segments import PolygonValue
from .models.creating_segments import Segment
from .models.creating_segments import TargetPoint
from .intersection_handlers.containment_handler import ContainmentHandler
from .intersection_handlers.many_points_overlap_handler import ManyPointsOverlapHandler
from .intersection_handlers.two_points_overlap_handler import TwoPointsOverlapHandler

CALCULATION_NAME = 'Расчёт сегментов\n'

logger = logging.getLogger('creating_segment_calculation_module')
POINT_DEDUP_TOLERANCE = 1e-9
SHARED_EDGE_TOLERANCE = 1e-9
# Допуск на «нулевую» площадь пересечения.
# Два полигона с общей стороной теоретически пересекаются по линии (area == 0),
# но из-за погрешности double shapely может возвращать микроскопическую
# ненулевую площадь. При типичном масштабе координат задачи (~1e4) и длинах
# сторон ~1e3 шум на общей границе даёт ложную площадь до ~1e-6. Значение 1e-5
# надёжно покрывает этот шум с небольшим запасом и при этом много меньше
# площади любого геометрически осмысленного пересечения (минимум в тестах —
# 5000, запас >8 порядков).
BOUNDARY_TOUCH_AREA_TOLERANCE = 1e-5
PERIMETER_AREA_THRESHOLD = 0.5

def validate_and_process_lines(polygon_line: PolygonLine, polygon_name: str) -> tuple[list[Polygon], list[str]]:
    """Проверяет линии на валидность и преобразует в полигоны"""
    valid_polygons = []
    warnings = []

    for i, line in enumerate(polygon_line.lines):
        points = line.points

        # Проверка количества точек
        if len(points) < 4:
            warnings.append(
                f'{CALCULATION_NAME}'
                f'Полигон {polygon_name} в параметре Внешний контур содержит 3 или менее точек, расчёт будет выполнен без их учёта',
            )
            continue

        # Проверка замкнутости
        first_point = points[0]
        last_point = points[-1]
        if (first_point.x != last_point.x) or (first_point.y != last_point.y):
            warnings.append(
                f'{CALCULATION_NAME}'
                f'Полигон {polygon_name} в параметре Внешний контур имеет незамкнутые полилинии, расчёт будет выполнен без их учёта',
            )
            continue

        # Создание полигона Shapely
        try:
            poly = Polygon([(p.x, p.y) for p in points])
            if not poly.is_valid:
                warnings.append(
                    f'{CALCULATION_NAME}'
                    f'Полигон {polygon_name}: Полилиния {i + 1} имеет некорректную геометрию - исключена',
                )
                continue

            valid_polygons.append(poly)
        except Exception:
            warnings.append(
                f'{CALCULATION_NAME}Полигон {polygon_name}: Неизвестная ошибка создания полилинии {i + 1} - исключена',
            )

    return valid_polygons, warnings


def clip_to_model_border(
    polygons: list[Polygon],
    model_border: Polygon | None,
    polygon_name: str,
) -> tuple[list[Polygon], list[str]]:
    """Обрезает полигоны по контуру модели"""
    if model_border is None:
        return polygons, []

    result_polygons = []
    warnings = []

    for i, poly in enumerate(polygons):
        # Проверка отношения к контуру модели
        if model_border.contains(poly):
            result_polygons.append(poly)
        elif not model_border.intersects(poly):
            warnings.append(
                f'{CALCULATION_NAME}'
                f'Полигон {polygon_name} в параметре Полигоны не входит в границы модели пласта, расчёт будет продолжен без её учёта.',
            )
        else:
            try:
                # Выполняем обрезку
                intersection = model_border.intersection(poly)

                if intersection.is_empty:
                    warnings.append(
                        f'{CALCULATION_NAME}'
                        f'Полигон {polygon_name}: Полилиния {i + 1} не пересекает контур модели - исключена',
                    )
                elif intersection.geom_type == 'Polygon':
                    result_polygons.append(intersection)
                elif intersection.geom_type == 'MultiPolygon':
                    # Выбираем наибольший полигон из результата
                    largest = max(intersection.geoms, key=lambda g: g.area)
                    result_polygons.append(largest)
                else:
                    warnings.append(
                        f'{CALCULATION_NAME}'
                        f'Полигон {polygon_name}: Полилиния {i + 1} имеет неподдерживаемый тип после обрезки - исключена',
                    )
            except Exception as e:
                warnings.append(
                    f'{CALCULATION_NAME}Полигон {polygon_name}: Ошибка обрезки полилинии {i + 1}: {e!s} - исключена',
                )

    return result_polygons, warnings


def _rebuild_outer_polygon_for_containment(outer_polygon: Polygon, inner_polygon: Polygon) -> BaseGeometry:
    """Строит внешний полигон с отверстием (выделено для тестирования ветки ошибок)."""
    return outer_polygon.difference(inner_polygon)


_CONTAINMENT_HANDLER = ContainmentHandler()
_TWO_POINTS_HANDLER = TwoPointsOverlapHandler(
    point_dedup_tolerance=POINT_DEDUP_TOLERANCE,
    shared_edge_tolerance=SHARED_EDGE_TOLERANCE,
    boundary_touch_area_tolerance=BOUNDARY_TOUCH_AREA_TOLERANCE,
)
_MANY_POINTS_HANDLER = ManyPointsOverlapHandler(
    boundary_touch_area_tolerance=BOUNDARY_TOUCH_AREA_TOLERANCE,
    perimeter_area_threshold=PERIMETER_AREA_THRESHOLD,
)


def handle_containment(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
) -> ContainmentHandlingResult:
    """Обрабатывает пару как потенциальную вложенность.

    Args:
        polygons: Список полигонов для мутации.
        first_index: Индекс первого полигона.
        second_index: Индекс второго полигона.

    Returns:
        Результат обработки вложенности.
    """
    return _CONTAINMENT_HANDLER.handle(
        polygons=polygons,
        first_index=first_index,
        second_index=second_index,
    )


def handle_two_points_intersection(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
    first_intersection_point: Point,
    second_intersection_point: Point,
) -> bool:
    """Обрабатывает пару в сценарии двух граничных точек пересечения.

    Args:
        polygons: Список полигонов для мутации.
        first_index: Индекс первого полигона.
        second_index: Индекс второго полигона.
        first_intersection_point: Первая точка разреза.
        second_intersection_point: Вторая точка разреза.

    Returns:
        True, если пара успешно перестроена; False — если перестроить не удалось.
    """
    return _TWO_POINTS_HANDLER.handle(
        polygons=polygons,
        first_index=first_index,
        second_index=second_index,
        first_intersection_point=first_intersection_point,
        second_intersection_point=second_intersection_point,
    )


def handle_many_points_intersection(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
) -> bool:
    """Обрабатывает пару fallback-веткой сложного пересечения.

    Args:
        polygons: Список полигонов для мутации.
        first_index: Индекс первого полигона.
        second_index: Индекс второго полигона.

    Returns:
        True, если пара успешно перестроена; False — если перестроить не удалось.
    """
    return _MANY_POINTS_HANDLER.handle(
        polygons=polygons,
        first_index=first_index,
        second_index=second_index,
    )


def _build_rebuild_failed_warning(polygon_name: str) -> str:
    """Формирует сообщение об ошибке универсальной перестройки пары."""
    return (
        f'{CALCULATION_NAME}'
        f'Полилинии полигона {polygon_name} со сложным пересечением '
        f'не удалось перестроить, обе полилинии исключены из расчёта.'
    )


def _build_containment_failure_warning(polygon_name: str) -> str:
    """Формирует сообщение об ошибке обработки вложенности."""
    return (
        f'{CALCULATION_NAME}'
        f'Полилиния полигона {polygon_name} исключена из расчёта из-за ошибки обработки вложенности.'
    )


@dataclass(frozen=True, slots=True)
class OverlapClassification:
    """Результат классификации пересечения пары полигонов."""

    case: OverlapCase
    shared_boundary_vertices: tuple[Point, Point] | None = None

def point_on_boundary(polygon: Polygon, point: Point, tolerance: float = 1e-9) -> bool:
    return polygon.boundary.buffer(tolerance).covers(point)


def find_significant_overlaps(first_polygon: Polygon, second_polygon: Polygon) -> list[Polygon]:
    def collect_polygon_components(geometry: BaseGeometry) -> list[Polygon]:
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
                polygons.extend(collect_polygon_components(part))
            return polygons

        return polygons

    intersection_geometry = first_polygon.intersection(second_polygon)

    overlap_polygons = collect_polygon_components(intersection_geometry)

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

        if shared_boundary_vertex_count == 0:
            return OverlapClassification(case=OverlapCase.all_points_inside_one_polygon)

        if len(vertex_info) == 3 and shared_boundary_vertex_count == 2 and inside_vertex_count == 1:
            return OverlapClassification(
                case=OverlapCase.candidate_block_4,
                shared_boundary_vertices=(shared_boundary_vertices[0], shared_boundary_vertices[1]),
            )

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
def _drop_excluded_polygons(
    polygons: list[Polygon],
    excluded_indexes: set[int],
) -> list[Polygon]:
    result_polygons: list[Polygon] = []

    for polygon_index, polygon in enumerate(polygons):
        if polygon_index in excluded_indexes:
            continue
        result_polygons.append(polygon)

    return result_polygons

def process_intersections_rebuild(
    polygons: list[Polygon],
    polygon_name: str,
) -> tuple[list[Polygon], list[str]]:
    """Перестраивает пересекающиеся полигоны до попарной непересекаемости.

    Args:
        polygons: Исходные полигоны.
        polygon_name: Имя полигона для текстов предупреждений.

    Returns:
        Кортеж из перестроенных полигонов и предупреждений.
    """
    warnings: list[str] = []
    current_polygons = list(polygons)
    excluded_indexes: set[int] = set()

    while True:
        should_restart_scan = False

        for first_polygon_index in range(len(current_polygons)):
            if first_polygon_index in excluded_indexes:
                continue

            for second_polygon_index in range(first_polygon_index + 1, len(current_polygons)):
                if second_polygon_index in excluded_indexes:
                    continue

                first_polygon = current_polygons[first_polygon_index]
                second_polygon = current_polygons[second_polygon_index]
                classification = _classify_pair(first_polygon, second_polygon)

                # Значимого площадного пересечения нет: либо полигоны не пересекаются,
                # либо касаются по границе в пределах численного шума.
                if classification.case == OverlapCase.no_overlap:
                    continue

                # Классификатор не смог распознать структуру оверлапа, эту пару
                # безопасно обработать нельзя — исключаем оба полигона.
                if classification.case == OverlapCase.unsupported:
                    warnings.append(
                        f'{CALCULATION_NAME}'
                        f'Полилинии полигона {polygon_name} имеют неподдерживаемый тип пересечения — '
                        f'обе полилинии исключены из расчёта.'
                    )
                    excluded_indexes.update({first_polygon_index, second_polygon_index})
                    break

                # Вложенность: один полигон внутри другого, обрабатываем отдельным handler'ом.
                if classification.case == OverlapCase.all_points_inside_one_polygon:
                    containment_result = handle_containment(
                        polygons=current_polygons,
                        first_index=first_polygon_index,
                        second_index=second_polygon_index,
                    )
                    if containment_result.status == ContainmentHandlingStatus.rebuilt:
                        # Список не менялся по длине, индексы валидны, двигаемся дальше.
                        continue
                    if containment_result.status == ContainmentHandlingStatus.exclude_outer:
                        warnings.append(_build_containment_failure_warning(polygon_name))
                        outer_index = containment_result.outer_index
                        if outer_index is not None:
                            excluded_indexes.add(outer_index)
                        # Если исключили текущий внешний индекс, продолжать внутренний цикл бессмысленно.
                        if outer_index == first_polygon_index:
                            break
                        continue
                    # Защита от рассинхрона: если handler вернул not_containment, идём в fallback ниже.

                # «Чистое» пересечение для block 4: две граничные вершины уже определены классификатором.
                if classification.case == OverlapCase.candidate_block_4:
                    if classification.shared_boundary_vertices is not None:
                        first_vertex, second_vertex = classification.shared_boundary_vertices
                        two_points_rebuilt = handle_two_points_intersection(
                            polygons=current_polygons,
                            first_index=first_polygon_index,
                            second_index=second_polygon_index,
                            first_intersection_point=first_vertex,
                            second_intersection_point=second_vertex,
                        )
                        if two_points_rebuilt:
                            # Длина списка не изменилась, можно идти к следующей паре.
                            continue

                # Fallback на block 5: handler может изменить длину списка полигонов.
                many_points_rebuilt = handle_many_points_intersection(
                    polygons=current_polygons,
                    first_index=first_polygon_index,
                    second_index=second_polygon_index,
                )
                if many_points_rebuilt:
                    # После изменения длины списка старые индексы ненадёжны, нужен полный restart сканирования.
                    should_restart_scan = True
                    break

                # Ни один способ перестройки не сработал — исключаем пару.
                warnings.append(_build_rebuild_failed_warning(polygon_name))
                excluded_indexes.update({first_polygon_index, second_polygon_index})
                break

            if should_restart_scan:
                break

        if not should_restart_scan:
            break

        current_polygons = _drop_excluded_polygons(current_polygons, excluded_indexes)
        excluded_indexes = set()

    result_polygons = _drop_excluded_polygons(current_polygons, excluded_indexes)
    return result_polygons, warnings


def check_intersections(polygons: list[Polygon], polygon_name: str) -> tuple[list[Polygon], list[str]]:
    """Проверяет полигоны на пересечения и последовательно обрабатывает пары."""
    warnings: list[str] = []
    excluded_indexes: set[int] = set()

    for first_index in range(len(polygons)):
        if first_index in excluded_indexes:
            continue
        for second_index in range(first_index + 1, len(polygons)):
            if second_index in excluded_indexes:
                continue
            first_polygon = polygons[first_index]
            second_polygon = polygons[second_index]

            if not first_polygon.intersects(second_polygon):
                continue

            # Вычисляем область пересечения
            intersection = first_polygon.intersection(second_polygon)

            # Проверяем, что пересечение имеет площадь (не только граница)
            if intersection.area <= BOUNDARY_TOUCH_AREA_TOLERANCE:
                continue

            excluded_indexes.update({first_index, second_index})
            warnings.append(
                f'{CALCULATION_NAME}'
                f'Полилинии полигона {polygon_name} в параметре Полигоны пересекаются между собой, '
                f'расчёт будет продолжен без её (их) учёта.',
            )
            break

    result_polygons = [polygon for index, polygon in enumerate(polygons) if index not in excluded_indexes]
    return result_polygons, warnings


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


def polygon_to_polygon_line(polygon: Polygon) -> PolygonLine:
    """Преобразует Shapely Polygon в PolygonLine с учётом внутренних контуров."""
    lines: list[Line] = []

    exterior_points = [TargetPoint(x=coord[0], y=coord[1]) for coord in polygon.exterior.coords]
    lines.append(Line(points=exterior_points))

    for interior in polygon.interiors:
        interior_points = [TargetPoint(x=coord[0], y=coord[1]) for coord in interior.coords]
        lines.append(Line(points=interior_points))

    return PolygonLine(lines=lines)


def assign_segment_names(polygons: list[Polygon], input_data: CalculationInput, storage) -> list[Segment]:
    """Назначает имена сегментам и формирует результат"""
    segments = []
    name_counter: dict[str, int] = {}

    for index, polygon in enumerate(polygons):
        # Формирование имени в зависимости от типа
        if input_data.parameter.name_by == SEGMENT_TYPE_NAME_ENUM.polygon_name:
            base_name = input_data.polygon.name
            name = f'{base_name} ({index + 1})' if index > 0 else base_name
        else:
            # Поиск скважин, принадлежащих полигону
            well_names = get_well_in_segment(input_data, polygon)
            name = generate_combined_name(well_names, name_counter)

        # Сохранение полигона в файл
        polygon_data = polygon_to_polygon_line(polygon).model_dump()
        content = json.dumps(polygon_data, ensure_ascii=False, indent=2)

        # Создаем имя файла без запрещенных символов
        safe_name = ''.join(c for c in name if c.isalnum() or c in ' _-')
        file_path = storage.get_temp_dir() / f'{safe_name}_{input_data.parameter.segments_type}.json'

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        segments.append(
            Segment(
                group=input_data.parameter.segments_group,
                type=input_data.parameter.segments_type,
                name=name,
                value=PolygonValue(file=File(path=str(file_path))),
                polygon_id=input_data.polygon.id,
            ),
        )

    return segments


def generate_combined_name(well_names: list[str], name_counter: dict[str, int]):
    """Генерируем имя сегманта."""
    if not well_names:
        base = 'Сегмент'
        count = name_counter.get(base, 0) + 1
        name_counter[base] = count
        return base if count == 1 else f'{base} ({count})'
    if len(well_names) == 1:
        return well_names[0]
    result = ''
    for name in well_names:
        candidate = name if not result else f'{result}_{name}'
        if len(candidate) <= 20:
            result = candidate
        else:
            break
    return result or well_names[0]


def get_well_in_segment(input_data: CalculationInput, polygon: Polygon) -> list[str]:
    """Определяет скважины, принадлежащие сегменту"""
    well_names = []
    for well in input_data.well:
        # Для скважин с одной точкой
        if len(well.target.point) == 1:
            point = Point(well.target.point[0].x, well.target.point[0].y)
            if polygon.contains(point):
                well_names.append(well.name)

        # Для скважин с двумя точками
        elif len(well.target.point) >= 2:
            point1, point2 = well.target.point[0], well.target.point[1]
            line = LineString([(point1.x, point1.y), (point2.x, point2.y)])

            # Проверка доли вхождения
            intersection = polygon.intersection(line)
            if not intersection.is_empty:
                total_length = line.length
                intersection_length = intersection.length
                fraction = intersection_length / total_length

                # Если gs_part не задан, считаем 100%
                min_fraction = input_data.parameter.gs_part or 1.0

                if fraction >= min_fraction:
                    well_names.append(well.name)
    return well_names


def creating_segments(input_data: CalculationInput, storage) -> CalculationResult:
    """Основная функция создания сегментов"""
    info_msgs: list[str] = []
    warning_msgs: list[str] = []
    error_msgs: list[str] = []

    try:
        # Загрузка основного полигона
        with open(input_data.polygon.value.file.path, encoding='utf-8') as f:
            polygon_data = json.load(f)
        polygon_line = PolygonLine.model_validate(polygon_data)

        # Валидация и обработка линий
        polygons, warnings = validate_and_process_lines(polygon_line, input_data.polygon.name)
        warning_msgs.extend(warnings)

        # Проверка наличия валидных полигонов
        if not polygons:
            error_msgs.append(
                f"{CALCULATION_NAME}"
                f"Все полилинии полигона '{input_data.polygon.name}' в параметре 'Внешний контур' не прошли валидацию. Расчёт не выполнен.",
            )
            return CalculationResult(formation=None, info=info_msgs, warning=warning_msgs, error=error_msgs)

        # Загрузка контура модели (если есть)
        model_border = None
        if input_data.formation_model and input_data.formation_model.border_model:
            try:
                with open(input_data.formation_model.border_model.file.path, encoding='utf-8') as f:
                    border_data = json.load(f)
                border_line = PolygonLine.model_validate(border_data)

                if border_line.lines:
                    border_points = [(p.x, p.y) for p in border_line.lines[0].points]
                    model_border = Polygon(border_points)

            except ValueError:
                error_msgs.append(
                    f'{CALCULATION_NAME}Неизвестный формат контура модели. Контур модели не будет использован.',
                )
        # Обрезка по контуру модели
        polygons, clip_warnings = clip_to_model_border(polygons, model_border, input_data.polygon.name)
        warning_msgs.extend(clip_warnings)

        if not polygons:
            error_msgs.append(
                f"{CALCULATION_NAME}"
                f"Все полилинии полигона '{input_data.polygon.name}' исключены после обрезки по контуру модели. Расчёт не выполнен.",
            )
            return CalculationResult(formation=None, info=info_msgs, warning=warning_msgs, error=error_msgs)

        if input_data.parameter.merge_radius > 0:
            polygons, merge_warnings, merge_infos = merge_by_radius(
                polygons,
                input_data.parameter.merge_radius,
                input_data.polygon.name,
            )
            warning_msgs.extend(merge_warnings)
            info_msgs.extend(merge_infos)


        if not polygons:
            error_msgs.append(
                f"{CALCULATION_NAME}"
                f"Все полилинии полигона '{input_data.polygon.name}' исключены после склейки по радиусу. Расчёт не выполнен.",
            )
            return CalculationResult(formation=None, info=info_msgs, warning=warning_msgs, error=error_msgs)

        # Проверка/обработка пересечений
        if input_data.parameter.process_intersections == 0:
            polygons, intersection_warnings = check_intersections(polygons, input_data.polygon.name)
        else:
            polygons, intersection_warnings = process_intersections_rebuild(polygons, input_data.polygon.name)
        warning_msgs.extend(intersection_warnings)

        if not polygons:
            error_msgs.append(
                f"{CALCULATION_NAME}"
                f"Все полилинии полигона '{input_data.polygon.name}' исключены из-за пересечений. Расчёт не выполнен.",
            )
            return CalculationResult(formation=None, info=info_msgs, warning=warning_msgs, error=error_msgs)

        # Формирование сегментов
        segments = assign_segment_names(polygons, input_data, storage)
        info_msgs.append(f'{CALCULATION_NAME}Успешно создано сегментов: {len(segments)}')

        return CalculationResult(
            formation=FormationResult(segment=segments, name=input_data.formation.name),
            info=info_msgs,
            warning=warning_msgs,
            error=error_msgs,
        )

    except Exception as e:
        import traceback

        error_msgs.append(
            f'{CALCULATION_NAME}'
            f'Неизвестная ошибка расчетного модуля: {e!s}\n'
            f'Трассировка в логах воркера расчетного сервиса.',
        )
        logger.error(
            f'{CALCULATION_NAME}Неизвестная ошибка расчетного модуля: {e!s}\nТрассировка: {traceback.format_exc()}',
        )
        return CalculationResult(formation=None, info=[], warning=warning_msgs, error=error_msgs)
