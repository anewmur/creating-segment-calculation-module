from shapely.geometry import Point
from shapely.geometry import Polygon

from .constants import BOUNDARY_TOUCH_AREA_TOLERANCE
from .constants import CALCULATION_NAME
from .constants import PERIMETER_AREA_THRESHOLD
from .constants import POINT_DEDUP_TOLERANCE
from .constants import SHARED_EDGE_TOLERANCE
from .intersection_handlers.containment_handler import ContainmentHandler
from .intersection_handlers.many_points_overlap_handler import ManyPointsOverlapHandler
from .intersection_handlers.two_points_overlap_handler import TwoPointsOverlapHandler
from .models.enumirations import (
    ContainmentHandlingResult,
    ContainmentHandlingStatus,
    OverlapCase,
)
from .overlap_classification import OverlapClassification
from .overlap_classification import _classify_pair

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
    # Поздний импорт нужен для обратной совместимости monkeypatch через фасад creating_segments.
    # Не переносить на уровень модуля: будет циклический импорт и сломаются старые patch-точки.
    from . import creating_segments

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
                classification: OverlapClassification = _classify_pair(first_polygon, second_polygon)

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
                    containment_result = creating_segments.handle_containment(
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
                        two_points_rebuilt = creating_segments.handle_two_points_intersection(
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
                many_points_rebuilt = creating_segments.handle_many_points_intersection(
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
