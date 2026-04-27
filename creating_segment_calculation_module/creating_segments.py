import json
import logging
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .models.creating_segments import CalculationInput
from .models.creating_segments import CalculationResult
from .models.creating_segments import FormationResult
from .models.creating_segments import PolygonLine

from .constants import BOUNDARY_TOUCH_AREA_TOLERANCE
from .constants import CALCULATION_NAME
from .constants import PERIMETER_AREA_THRESHOLD
from .constants import POINT_DEDUP_TOLERANCE
from .constants import SHARED_EDGE_TOLERANCE
from .models.enumirations import ContainmentHandlingResult
from .models.enumirations import ContainmentHandlingStatus
from .models.enumirations import OverlapCase
from .polygon_input_validation import remove_duplicate_lines_by_edges
from .polygon_input_validation import validate_and_process_lines
from .polygon_serialization import polygon_to_polygon_line
from .polygon_serialization import save_polygons_as_single_segment
from .border_clipping import clip_to_model_border
from .vertex_merging import merge_by_radius
from .well_assignment import generate_combined_name
from .well_assignment import get_well_in_segment
from .overlap_classification import classify_overlap_vertices
from .overlap_classification import classify_significant_overlaps
from .overlap_classification import find_significant_overlaps
from .overlap_classification import point_on_boundary
from .overlap_classification import OverlapClassification
from .overlap_classification import _classify_pair
from .intersection_processing import _build_containment_failure_warning
from .intersection_processing import _build_rebuild_failed_warning
from .intersection_processing import _drop_excluded_polygons
from .intersection_processing import check_intersections
from .intersection_processing import handle_containment
from .intersection_processing import handle_many_points_intersection
from .intersection_processing import handle_two_points_intersection
from .intersection_processing import process_intersections_rebuild

logger = logging.getLogger('creating_segment_calculation_module')


def _rebuild_outer_polygon_for_containment(outer_polygon: Polygon, inner_polygon: Polygon) -> BaseGeometry:
    """Строит внешний полигон с отверстием (выделено для тестирования ветки ошибок)."""
    return outer_polygon.difference(inner_polygon)

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
