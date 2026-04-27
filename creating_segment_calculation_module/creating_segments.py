import json
import logging
from dataclasses import dataclass
from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from .models.enumirations import (
    ContainmentHandlingResult, ContainmentHandlingStatus, OverlapCase
)

from .models.creating_segments import CalculationInput
from .models.creating_segments import CalculationResult
from .models.creating_segments import FormationResult
from .models.creating_segments import PolygonLine
from .intersection_handlers.containment_handler import ContainmentHandler
from .intersection_handlers.many_points_overlap_handler import ManyPointsOverlapHandler
from .intersection_handlers.two_points_overlap_handler import TwoPointsOverlapHandler

from .constants import BOUNDARY_TOUCH_AREA_TOLERANCE
from .constants import CALCULATION_NAME
from .constants import PERIMETER_AREA_THRESHOLD
from .constants import POINT_DEDUP_TOLERANCE
from .constants import SHARED_EDGE_TOLERANCE
from .polygon_input_validation import remove_duplicate_lines_by_edges
from .polygon_input_validation import validate_and_process_lines
from .polygon_serialization import polygon_to_polygon_line
from .polygon_serialization import save_polygons_as_single_segment
from .border_clipping import clip_to_model_border
from .vertex_merging import merge_by_radius
from .well_assignment import generate_combined_name
from .well_assignment import get_well_in_segment

logger = logging.getLogger('creating_segment_calculation_module')


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


def creating_segments(input_data: CalculationInput, storage) -> CalculationResult:
    """Основная функция создания сегментов"""
    info_msgs: list[str] = []
    warning_msgs: list[str] = []
    error_msgs: list[str] = []

    try:
        with open(input_data.polygon.value.file.path, encoding='utf-8') as f:
            polygon_data = json.load(f)
        polygon_line = PolygonLine.model_validate(polygon_data)
        polygon_line, duplicate_lines_warnings = remove_duplicate_lines_by_edges(
            polygon_line,
            input_data.polygon.name,
        )
        warning_msgs.extend(duplicate_lines_warnings)

        polygons, warnings = validate_and_process_lines(polygon_line, input_data.polygon.name)
        warning_msgs.extend(warnings)

        if not polygons:
            error_msgs.append(
                f"{CALCULATION_NAME}"
                f"Все полилинии полигона '{input_data.polygon.name}' в параметре 'Внешний контур' не прошли валидацию. Расчёт не выполнен.",
            )
            return CalculationResult(formation=None, info=info_msgs, warning=warning_msgs, error=error_msgs)

        model_border = None
        if input_data.formation_model and input_data.formation_model.border_model:
            try:
                with open(input_data.formation_model.border_model.file.path, encoding='utf-8') as f:
                    border_data = json.load(f)
                border_line = PolygonLine.model_validate(border_data)

                if border_line.lines:
                    border_points = [(point.x, point.y) for point in border_line.lines[0].points]
                    model_border = Polygon(border_points)

            except ValueError:
                error_msgs.append(
                    f'{CALCULATION_NAME}Неизвестный формат контура модели. Контур модели не будет использован.',
                )

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

        segments = save_polygons_as_single_segment(polygons, input_data, storage)
        info_msgs.append(f'{CALCULATION_NAME}Успешно создано сегментов: {len(polygons)}')

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
