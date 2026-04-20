import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import cast
from shapely.geometry import LineString
from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.errors import GEOSException
from shapely.ops import split
from shapely.ops import unary_union
from .models.enumirations import (
    TwoPointsRebuildStatus, ManyPointsRebuildStatus, ContainmentHandlingResult,
    ContainmentHandlingStatus, OverlapCase
)
from prototype.polygon_visualizer.handle_viz import plot_geometries_debug
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

_TWO_POINTS_REBUILD_FAILED = TwoPointsRebuildStatus.rebuild_failed
_MANY_POINTS_REBUILD_FAILED = ManyPointsRebuildStatus.rebuild_failed

def _collect_points_from_geometry(geometry) -> list[Point]:
    """Рекурсивно извлекает Point в порядке обхода геометрии."""
    if geometry.is_empty:
        return []

    if geometry.geom_type == 'Point':
        return [geometry]

    if geometry.geom_type == 'MultiPoint':
        return list(geometry.geoms)

    if not hasattr(geometry, 'geoms'):
        return []

    result: list[Point] = []
    for sub_geometry in geometry.geoms:
        result.extend(_collect_points_from_geometry(sub_geometry))
    return result


def _is_same_point(first_point: Point, second_point: Point, tolerance: float = POINT_DEDUP_TOLERANCE) -> bool:
    """Сравнивает точки с допуском."""
    return abs(first_point.x - second_point.x) <= tolerance and abs(first_point.y - second_point.y) <= tolerance


def _deduplicate_points(points: list[Point], tolerance: float = POINT_DEDUP_TOLERANCE) -> list[Point]:
    """Удаляет дубликаты точек с сохранением порядка первого появления."""
    unique_points: list[Point] = []
    for point in points:
        if any(_is_same_point(point, unique_point, tolerance) for unique_point in unique_points):
            continue
        unique_points.append(point)
    return unique_points


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


def extract_points(geometry) -> list[Point]:
    """
    Возвращает уникальные точки пересечения.
    """
    raw_points = _collect_points_from_geometry(geometry)
    return _deduplicate_points(raw_points)




def _rebuild_outer_polygon_for_containment(outer_polygon: Polygon, inner_polygon: Polygon) -> BaseGeometry:
    """Строит внешний полигон с отверстием (выделено для тестирования ветки ошибок)."""
    return outer_polygon.difference(inner_polygon)


def handle_containment(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
) -> ContainmentHandlingResult:
    """Обрабатывает вложенность: внутренний полигон остаётся, внешний получает отверстие."""
    first_polygon = polygons[first_index]
    second_polygon = polygons[second_index]

    if first_polygon.contains(second_polygon):
        outer_index = first_index
        inner_index = second_index
    elif second_polygon.contains(first_polygon):
        outer_index = second_index
        inner_index = first_index
    else:
        return ContainmentHandlingResult(status=ContainmentHandlingStatus.not_containment)

    outer_polygon = polygons[outer_index]
    inner_polygon = polygons[inner_index]
    rebuilt_outer = _rebuild_outer_polygon_for_containment(outer_polygon, inner_polygon)

    if (
        rebuilt_outer.is_empty
        or rebuilt_outer.geom_type != 'Polygon'
        or not rebuilt_outer.is_valid
        or len(rebuilt_outer.interiors) < 1
    ):
        return ContainmentHandlingResult(
            status=ContainmentHandlingStatus.exclude_outer,
            outer_index=outer_index,
        )

    polygons[outer_index] = rebuilt_outer
    return ContainmentHandlingResult(
        status=ContainmentHandlingStatus.rebuilt,
        outer_index=outer_index,
    )


def _as_rebuilt_polygon_or_none(geometry: BaseGeometry) -> Polygon | None:
    """Проверяет, что итог перестройки пары — валидный одиночный Polygon."""
    if geometry.is_empty or not geometry.is_valid:
        return None
    if geometry.geom_type != 'Polygon':
        return None
    return geometry


def _is_polygonal_geometry(geometry: BaseGeometry) -> bool:
    """Проверяет, что геометрия непустая, валидная и полигональная."""
    return geometry.geom_type in {'Polygon', 'MultiPolygon'} and geometry.is_valid and not geometry.is_empty


def _has_boundary_shared_segment(boundary_intersection: BaseGeometry) -> bool:
    """Проверяет наличие общих линейных частей границ положительной длины."""
    if boundary_intersection.is_empty:
        return False

    if boundary_intersection.geom_type in {'LineString', 'LinearRing'}:
        return boundary_intersection.length > POINT_DEDUP_TOLERANCE

    if boundary_intersection.geom_type == 'MultiLineString':
        return any(part.length > POINT_DEDUP_TOLERANCE for part in boundary_intersection.geoms)

    if boundary_intersection.geom_type == 'GeometryCollection':
        return any(_has_boundary_shared_segment(part) for part in boundary_intersection.geoms)

    return False


def _collect_split_halves(overlap: BaseGeometry, cut_segment: LineString) -> list[Polygon]:
    """Разрезает overlap и собирает валидные полигональные части."""
    try:
        split_result = split(overlap, cut_segment)
    except (GEOSException, TypeError, ValueError):
        # Для блока 4 любая ошибка split — допустимая деградация до rebuild_failed:
        # входные геометрии могут быть топологически сложными после difference/intersection.
        return []

    halves: list[Polygon] = []
    for geometry in split_result.geoms:
        if geometry.geom_type != 'Polygon':
            continue
        if not geometry.is_valid:
            continue
        if geometry.area <= BOUNDARY_TOUCH_AREA_TOLERANCE:
            continue
        halves.append(geometry)

    return halves


def _assign_half_to_polygon(half: Polygon, only_i: BaseGeometry, only_j: BaseGeometry) -> int | None:
    """
    Назначает половину перекрытия полигону:
    0 -> first polygon, 1 -> second polygon, None -> неоднозначно.
    """
    shared_len_with_i = half.boundary.intersection(only_i.boundary).length
    shared_len_with_j = half.boundary.intersection(only_j.boundary).length

    if shared_len_with_i > shared_len_with_j + SHARED_EDGE_TOLERANCE:
        return 0
    if shared_len_with_j > shared_len_with_i + SHARED_EDGE_TOLERANCE:
        return 1

    return None


def _build_cut_segment(first_point: Point, second_point: Point) -> LineString:
    """Строит отрезок разреза между двумя точками пересечения границ."""
    return LineString([(first_point.x, first_point.y), (second_point.x, second_point.y)])


def _segment_matches_polygon_boundary(
    polygon: Polygon,
    cut_segment: LineString,
) -> bool:
    """Проверяет, что отрезок разреза целиком лежит на границе полигона."""
    return polygon.boundary.buffer(POINT_DEDUP_TOLERANCE).covers(cut_segment)


def _validate_two_point_rebuild_inputs(
    poly_i: Polygon,
    poly_j: Polygon,
) -> tuple[BaseGeometry, BaseGeometry, BaseGeometry] | None:
    """Готовит only/overlap и валидирует полигональность для алгоритма блока 4."""
    only_i = poly_i.difference(poly_j)
    only_j = poly_j.difference(poly_i)
    overlap = poly_i.intersection(poly_j)

    if not _is_polygonal_geometry(only_i):
        return None
    if not _is_polygonal_geometry(only_j):
        return None
    if not _is_polygonal_geometry(overlap):
        return None

    return only_i, only_j, overlap


def _rebuild_polygons_from_overlap(
    only_i: BaseGeometry,
    only_j: BaseGeometry,
    overlap: BaseGeometry,
    cut_segment: LineString,
) -> tuple[Polygon, Polygon] | None:
    """Разрезает overlap и собирает новые полигоны для пары."""
    halves = _collect_split_halves(overlap, cut_segment)
    if len(halves) != 2:
        return None

    half_for_i: Polygon | None = None
    half_for_j: Polygon | None = None
    for half in halves:
        assignment = _assign_half_to_polygon(half, only_i, only_j)
        if assignment is None:
            return None
        if assignment == 0:
            if half_for_i is not None:
                return None
            half_for_i = half
            continue
        if half_for_j is not None:
            return None
        half_for_j = half

    if half_for_i is None or half_for_j is None:
        return None

    new_poly_i = _as_rebuilt_polygon_or_none(unary_union([only_i, half_for_i]))
    new_poly_j = _as_rebuilt_polygon_or_none(unary_union([only_j, half_for_j]))
    if new_poly_i is None or new_poly_j is None:
        return None

    return new_poly_i, new_poly_j


def _rebuild_other_by_fixed_boundary_polygon(
    polygons: list[Polygon],
    fixed_index: int,
    other_index: int,
) -> TwoPointsRebuildStatus:
    """Оставляет fixed polygon без изменений и убирает overlap у второй фигуры."""
    fixed_polygon = polygons[fixed_index]
    other_polygon = polygons[other_index]

    new_other_geom = other_polygon.difference(fixed_polygon)
    new_other = _as_rebuilt_polygon_or_none(new_other_geom)
    if new_other is None:
        return _TWO_POINTS_REBUILD_FAILED

    if fixed_polygon.intersection(new_other).area > BOUNDARY_TOUCH_AREA_TOLERANCE:
        return _TWO_POINTS_REBUILD_FAILED

    union_area = fixed_polygon.union(other_polygon).area
    if union_area <= 0:
        return _TWO_POINTS_REBUILD_FAILED

    rebuilt_area = fixed_polygon.area + new_other.area
    if abs(rebuilt_area - union_area) > 1e-6 * union_area:
        return _TWO_POINTS_REBUILD_FAILED

    polygons[fixed_index] = fixed_polygon
    polygons[other_index] = new_other
    return TwoPointsRebuildStatus.rebuilt


def _validate_rebuilt_pair(
    poly_i: Polygon,
    poly_j: Polygon,
    new_poly_i: Polygon,
    new_poly_j: Polygon,
) -> bool:
    """Проверяет постусловия перестройки пары в блоке 4."""
    if not new_poly_i.is_valid or not new_poly_j.is_valid:
        return False
    if new_poly_i.intersection(new_poly_j).area > BOUNDARY_TOUCH_AREA_TOLERANCE:
        return False

    union_area = poly_i.union(poly_j).area
    if union_area <= 0:
        return False

    rebuilt_area = new_poly_i.area + new_poly_j.area
    if abs(rebuilt_area - union_area) > 1e-6 * union_area:
        return False

    shared_boundary_length = new_poly_i.boundary.intersection(new_poly_j.boundary).length
    return shared_boundary_length > POINT_DEDUP_TOLERANCE


def handle_two_points_intersection(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
    first_intersection_point: Point,
    second_intersection_point: Point,
) -> TwoPointsRebuildStatus:
    """
    Перестраивает пару полигонов в сценарии «2 точки пересечения, без общих отрезков».
    """
    cut_segment = _build_cut_segment(first_intersection_point, second_intersection_point)
    if cut_segment is None:
        return _TWO_POINTS_REBUILD_FAILED

    poly_i = polygons[first_index]
    poly_j = polygons[second_index]
    cut_on_first = _segment_matches_polygon_boundary(poly_i, cut_segment)
    cut_on_second = _segment_matches_polygon_boundary(poly_j, cut_segment)

    if cut_on_first and not cut_on_second:
        return _rebuild_other_by_fixed_boundary_polygon(
            polygons=polygons,
            fixed_index=first_index,
            other_index=second_index,
        )

    if cut_on_second and not cut_on_first:
        return _rebuild_other_by_fixed_boundary_polygon(
            polygons=polygons,
            fixed_index=second_index,
            other_index=first_index,
        )

    if cut_on_first and cut_on_second:
        return _TWO_POINTS_REBUILD_FAILED

    prepared_geometries = _validate_two_point_rebuild_inputs(poly_i, poly_j)
    if prepared_geometries is None:
        return _TWO_POINTS_REBUILD_FAILED

    only_i, only_j, overlap = prepared_geometries
    rebuilt_pair = _rebuild_polygons_from_overlap(only_i, only_j, overlap, cut_segment)
    if rebuilt_pair is None:
        return _TWO_POINTS_REBUILD_FAILED

    new_poly_i, new_poly_j = rebuilt_pair
    if not _validate_rebuilt_pair(poly_i, poly_j, new_poly_i, new_poly_j):
        return _TWO_POINTS_REBUILD_FAILED

    polygons[first_index] = new_poly_i
    polygons[second_index] = new_poly_j
    return TwoPointsRebuildResult(status=TwoPointsRebuildStatus.rebuilt)


def _collect_polygon_components(geometry: BaseGeometry) -> list[Polygon]:
    """Рекурсивно собирает валидные полигональные компоненты из геометрии."""
    polygons: list[Polygon] = []

    if geometry.is_empty:
        return polygons

    if geometry.geom_type == 'Polygon':
        if geometry.is_valid and geometry.area > BOUNDARY_TOUCH_AREA_TOLERANCE:
            polygons.append(geometry)
        return polygons

    if geometry.geom_type == 'MultiPolygon':
        for polygon in geometry.geoms:
            if polygon.is_valid and polygon.area > BOUNDARY_TOUCH_AREA_TOLERANCE:
                polygons.append(polygon)
        return polygons

    if geometry.geom_type == 'GeometryCollection':
        for polygon in geometry.geoms:
            polygons.extend(_collect_polygon_components(polygon))
        return polygons

    return polygons


def _passes_perimeter_area_filter(polygon: Polygon) -> bool:
    """Проверяет, что отношение периметра к площади не превышает порог."""
    if not polygon.is_valid:
        return False
    if polygon.is_empty:
        return False
    if polygon.area <= BOUNDARY_TOUCH_AREA_TOLERANCE:
        return False
    return polygon.length / polygon.area <= PERIMETER_AREA_THRESHOLD


def _replace_pair_with_polygons(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
    replacement_polygons: list[Polygon],
) -> None:
    """Заменяет пару исходных полигонов списком новых. Индексы могут быть несоседними."""
    # Удаляем с большего индекса, чтобы не сдвинуть меньший.
    larger_index = max(first_index, second_index)
    smaller_index = min(first_index, second_index)
    del polygons[larger_index]
    del polygons[smaller_index]
    polygons[smaller_index:smaller_index] = replacement_polygons




def _get_valid_intersection_geometry(
    poly_i: Polygon,
    poly_j: Polygon,
) -> BaseGeometry | None:
    """Возвращает валидное полигональное пересечение."""
    if poly_i.area <= 0 or poly_j.area <= 0:
        return None

    intersection_geom = poly_i.intersection(poly_j)
    if intersection_geom.is_empty:
        return None
    if not intersection_geom.is_valid:
        return None

    if intersection_geom.geom_type == 'GeometryCollection':
        polygonal_parts = _collect_polygon_components(intersection_geom)
        if not polygonal_parts:
            return None
        intersection_geom = unary_union(polygonal_parts)

    if intersection_geom.geom_type not in {'Polygon', 'MultiPolygon'}:
        return None
    if intersection_geom.area <= BOUNDARY_TOUCH_AREA_TOLERANCE:
        return None

    return intersection_geom


def _select_keeper_and_loser_indexes(
    poly_i: Polygon,
    poly_j: Polygon,
    intersection_geom: BaseGeometry,
    first_index: int,
    second_index: int,
) -> tuple[int, int]:
    """Выбирает сохраняемый и перестраиваемый полигоны."""
    ratio_i = intersection_geom.area / poly_i.area
    ratio_j = intersection_geom.area / poly_j.area

    if ratio_i <= ratio_j:
        return first_index, second_index
    return second_index, first_index


def _build_pre_filter_polygons(
    polygons: list[Polygon],
    keeper_index: int,
    loser_index: int,
    intersection_geom: BaseGeometry,
) -> list[Polygon] | None:
    """Строит полигоны до фильтра отношения периметра к площади."""
    keeper_polygon = polygons[keeper_index]
    loser_polygon = polygons[loser_index]
    loser_rebuilt_geom = loser_polygon.difference(intersection_geom)
    loser_parts = _collect_polygon_components(loser_rebuilt_geom)

    pre_filter_polygons = [keeper_polygon, *loser_parts]

    for polygon in pre_filter_polygons:
        if polygon.is_empty:
            return None
        if not polygon.is_valid:
            return None
        if polygon.area <= BOUNDARY_TOUCH_AREA_TOLERANCE:
            return None

    return pre_filter_polygons


def _polygons_have_no_significant_overlap(
    polygons: list[Polygon],
) -> bool:
    """Проверяет отсутствие значимого overlap между полигонами."""
    for first_part_index in range(len(polygons)):
        for second_part_index in range(first_part_index + 1, len(polygons)):
            overlap_area = (
                polygons[first_part_index]
                .intersection(polygons[second_part_index])
                .area
            )
            if overlap_area > BOUNDARY_TOUCH_AREA_TOLERANCE:
                return False
    return True


def _areas_match_original_union(
    poly_i: Polygon,
    poly_j: Polygon,
    rebuilt_polygons: list[Polygon],
) -> bool:
    """Проверяет сохранение суммарной площади объединения."""
    original_union_area = poly_i.union(poly_j).area
    if original_union_area <= 0:
        return False

    rebuilt_area = sum(polygon.area for polygon in rebuilt_polygons)
    return abs(rebuilt_area - original_union_area) <= 1e-6 * original_union_area


def _filter_replacement_polygons(
    polygons: list[Polygon],
) -> list[Polygon]:
    """Оставляет полигоны, прошедшие фильтр формы."""
    replacement_polygons: list[Polygon] = []

    for polygon in polygons:
        if _passes_perimeter_area_filter(polygon):
            replacement_polygons.append(polygon)

    return replacement_polygons


def handle_many_points_intersection(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
) -> ManyPointsRebuildStatus:
    """Перестраивает пару при сложном пересечении."""
    poly_i = polygons[first_index]
    poly_j = polygons[second_index]

    intersection_geom = _get_valid_intersection_geometry(poly_i, poly_j)
    if intersection_geom is None:
        return _MANY_POINTS_REBUILD_FAILED

    keeper_index, loser_index = _select_keeper_and_loser_indexes(
        poly_i,
        poly_j,
        intersection_geom,
        first_index,
        second_index,
    )

    pre_filter_polygons = _build_pre_filter_polygons(
        polygons,
        keeper_index,
        loser_index,
        intersection_geom,
    )
    if pre_filter_polygons is None:
        return _MANY_POINTS_REBUILD_FAILED

    if not _polygons_have_no_significant_overlap(pre_filter_polygons):
        return _MANY_POINTS_REBUILD_FAILED

    if not _areas_match_original_union(poly_i, poly_j, pre_filter_polygons):
        return _MANY_POINTS_REBUILD_FAILED

    replacement_polygons = _filter_replacement_polygons(pre_filter_polygons)
    _replace_pair_with_polygons(
        polygons=polygons,
        first_index=first_index,
        second_index=second_index,
        replacement_polygons=replacement_polygons,
    )
    return ManyPointsRebuildStatus.rebuilt


def _pair_has_significant_area_overlap(
    first_polygon: Polygon,
    second_polygon: Polygon,
) -> bool:
    """Проверяет, что пара имеет площадное пересечение выше допуска шума на границе."""
    if not first_polygon.intersects(second_polygon):
        return False
    intersection_geom = first_polygon.intersection(second_polygon)
    if intersection_geom.is_empty:
        return False
    return intersection_geom.area > BOUNDARY_TOUCH_AREA_TOLERANCE


def _try_handle_two_points_branch(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
    intersection_points: list[Point],
    boundary_intersection: BaseGeometry,
) -> bool:
    """Пытается перестроить пару блоком 4. Возвращает True, если перестроено."""
    # Блок 4 применим только для «чистого» 2-точечного пересечения без общих отрезков.
    if len(intersection_points) != 2:
        return False
    if _has_boundary_shared_segment(boundary_intersection):
        return False

    first_point, second_point = intersection_points
    outcome = handle_two_points_intersection(
        polygons=polygons,
        first_index=first_index,
        second_index=second_index,
        first_intersection_point=first_point,
        second_intersection_point=second_point,
    )
    return outcome.status == TwoPointsRebuildStatus.rebuilt


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


class _PairOutcome(Enum):
    """Итог обработки одной пары полигонов в dispatcher'е."""

    rebuilt_in_place = 'rebuilt_in_place'
    rebuilt_with_restart = 'rebuilt_with_restart'
    excluded = 'excluded'
    containment_failure_outer_excluded = 'containment_failure_outer_excluded'


@dataclass(frozen=True, slots=True)
class _PairDispatchResult:
    """Результат обработки одной пары: что делать дальше и какие индексы трогать."""

    outcome: _PairOutcome
    excluded_indexes: frozenset[int] = frozenset()


def collect_polygon_components(geometry: BaseGeometry) -> list[Polygon]:
    polygons: list[Polygon] = []

    if geometry.is_empty:
        return polygons

    if geometry.geom_type == "Polygon":
        polygons.append(cast(Polygon, geometry))
        return polygons

    if geometry.geom_type == "MultiPolygon":
        for polygon in geometry.geoms:
            polygons.append(cast(Polygon, polygon))
        return polygons

    if geometry.geom_type == "GeometryCollection":
        for part in geometry.geoms:
            polygons.extend(collect_polygon_components(part))
        return polygons

    return polygons

def point_on_boundary(polygon: Polygon, point: Point, tolerance: float = 1e-9) -> bool:
    return polygon.boundary.buffer(tolerance).covers(point)


def find_significant_overlaps(first_polygon, second_polygon):
    intersection_geometry = first_polygon.intersection(second_polygon)

    overlap_polygons = collect_polygon_components(intersection_geometry)

    plot_geometries_debug(
        [
            ("first boundary", overlap_polygons[0].boundary),
        ],
        title="boundary debug",
    )

    epsilon = 1e-5
    significant_overlaps = []

    for polygon in overlap_polygons:
        if polygon.area > epsilon:
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
) -> OverlapCase:
    for overlap_polygon in significant_overlaps:
        vertex_info = classify_overlap_vertices(
            overlap_polygon=overlap_polygon,
            first_polygon=first_polygon,
            second_polygon=second_polygon,
        )

        shared_boundary_vertex_count = 0
        inside_vertex_count = 0

        for item in vertex_info:
            on_first_boundary = item["on_first_boundary"]
            on_second_boundary = item["on_second_boundary"]

            if on_first_boundary and on_second_boundary:
                shared_boundary_vertex_count += 1
            else:
                inside_vertex_count += 1

        if shared_boundary_vertex_count == 0:
            return OverlapCase.all_points_inside_one_polygon

        if len(vertex_info) == 3 and shared_boundary_vertex_count == 2 and inside_vertex_count == 1:
            return OverlapCase.candidate_block_4

        if len(vertex_info) > 3 or shared_boundary_vertex_count > 2:
            return OverlapCase.candidate_block_5

    return OverlapCase.unsupported

def _dispatch_pair(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
    polygon_name: str,
    warnings: list[str],
) -> _PairDispatchResult:
    first_polygon = polygons[first_index]
    second_polygon = polygons[second_index]

    significant_overlaps = find_significant_overlaps(first_polygon, second_polygon)

    for overlap_polygon in significant_overlaps:
        OverlapCase = classify_significant_overlaps(
            significant_overlaps=significant_overlaps,
            first_polygon=first_polygon,
            second_polygon=second_polygon,
        )
    return _PairDispatchResult(outcome=_PairOutcome.excluded)

def _dispatch_pair_old(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
    polygon_name: str,
    warnings: list[str],
) -> _PairDispatchResult:
    """Подбирает подходящий блок обработки для пары и применяет его.

    Порядок: containment → блок 4 → блок 5 как универсальный fallback.
    Побочные эффекты: warnings пополняется при исключениях.
    """
    first_polygon = polygons[first_index]
    second_polygon = polygons[second_index]

    boundary_intersection = first_polygon.boundary.intersection(second_polygon.boundary)

    plot_geometries_debug(
        [
            ("first boundary", first_polygon.boundary),
            ("second boundary", second_polygon.boundary),
            ("intersection", boundary_intersection),
        ],
        title="boundary debug",
    )
    intersection_points = extract_points(boundary_intersection)



    if first_polygon.contains(second_polygon) or second_polygon.contains(first_polygon):
        containment_result = handle_containment(
            polygons=polygons,
            first_index=first_index,
            second_index=second_index,
        )
        if containment_result.status == ContainmentHandlingStatus.rebuilt:
            return _PairDispatchResult(outcome=_PairOutcome.rebuilt_in_place)
        if containment_result.status == ContainmentHandlingStatus.exclude_outer:
            warnings.append(_build_containment_failure_warning(polygon_name))
            outer_index = containment_result.outer_index
            excluded = frozenset({outer_index}) if outer_index is not None else frozenset()
            return _PairDispatchResult(
                outcome=_PairOutcome.containment_failure_outer_excluded,
                excluded_indexes=excluded,
            )
        # not_containment: проваливаемся дальше по алгоритму.

    if _try_handle_two_points_branch(
        polygons=polygons,
        first_index=first_index,
        second_index=second_index,
        intersection_points=intersection_points,
        boundary_intersection=boundary_intersection,
    ):
        return _PairDispatchResult(outcome=_PairOutcome.rebuilt_in_place)

    # Блок 5 — универсальный fallback. Он меняет длину списка полигонов,
    # поэтому при успехе внешний цикл обязан перезапустить скан.
    many_points_result = handle_many_points_intersection(
        polygons=polygons,
        first_index=first_index,
        second_index=second_index,
    )
    if many_points_result.status == ManyPointsRebuildStatus.rebuilt:
        return _PairDispatchResult(outcome=_PairOutcome.rebuilt_with_restart)

    warnings.append(_build_rebuild_failed_warning(polygon_name))


    return _PairDispatchResult(
        outcome=_PairOutcome.excluded,
        excluded_indexes=frozenset({first_index, second_index}),
    )


def process_intersections_rebuild(
    polygons: list[Polygon],
    polygon_name: str,
) -> tuple[list[Polygon], list[str]]:
    """Перестраивает пересекающиеся полигоны до попарной непересекаемости.

    Каждая пара направляется в одну из трёх веток: обработка вложенности,
    блок 4 (две точки без общего отрезка) или блок 5 как универсальный fallback.
    Перестройка блоком 5 меняет длину списка, поэтому скан перезапускается.
    """
    warnings: list[str] = []
    polygons = list(polygons)
    excluded_indexes: set[int] = set()

    while True:
        restart_scan = False
        for polygon_index in range(len(polygons)):
            if polygon_index in excluded_indexes:
                continue
            for other_index in range(polygon_index + 1, len(polygons)):
                if other_index in excluded_indexes:
                    continue
                if not _pair_has_significant_area_overlap(
                    polygons[polygon_index],
                    polygons[other_index],
                ):
                    continue
                # вызов диспетчера обработки пары полигонов.
                dispatch = _dispatch_pair(
                    polygons=polygons,
                    first_index=polygon_index,
                    second_index=other_index,
                    polygon_name=polygon_name,
                    warnings=warnings,
                )

                if dispatch.outcome == _PairOutcome.rebuilt_in_place:
                    continue
                if dispatch.outcome == _PairOutcome.rebuilt_with_restart:
                    restart_scan = True
                    break
                excluded_indexes.update(dispatch.excluded_indexes)
                if (
                    dispatch.outcome == _PairOutcome.containment_failure_outer_excluded
                    and polygon_index in dispatch.excluded_indexes
                ):
                    break
                if dispatch.outcome == _PairOutcome.excluded:
                    break

            if restart_scan:
                break

        if restart_scan:
            polygons = [p for i, p in enumerate(polygons) if i not in excluded_indexes]
            excluded_indexes = set()
            continue
        break

    return [p for i, p in enumerate(polygons) if i not in excluded_indexes], warnings


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


def _print_merge_group(
    group: list[tuple[int, int, float, float]],
) -> None:
    """Печатает группу склейки и целевую точку."""
    print(
        '[merge] group=',
        [
            {
                'polygon': polygon_index,
                'point': (vertex_x, vertex_y),
            }
            for polygon_index, _, vertex_x, vertex_y in group
        ],
    )
    # print(f'[merge] target=({avg_x}, {avg_y})')


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
            # print(
            #     f'[merge] polygon={polygon_index} point=({vertex_x}, {vertex_y}) '
            #     f'-> ({avg_x}, {avg_y})',
            # )
        else:
            already_x, already_y = planned_moves[vertex_key]
            # print(
            #     f'[merge] polygon={polygon_index} point=({vertex_x}, {vertex_y}) '
            #     f'already planned -> ({already_x}, {already_y})',
            # )


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
            print(
                f'[merge] skip for polygon={base_polygon_index} point=({base_x}, {base_y}): '
                f'more than one point from the same neighboring polygon',
            )
            continue

        group, avg_x, avg_y = _build_merge_group(
            base_polygon_index,
            base_vertex_index,
            base_x,
            base_y,
            neighbors,
        )
        # _print_merge_group(group)
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
            print(f'[merge] polygon={polygon_index} excluded after merge')
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