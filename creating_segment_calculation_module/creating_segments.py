import logging

from nedra_calculate_polygons.exceptions import ContourFileFormatError
from nedra_calculate_polygons.exceptions import ContourFileHasWrongSourceError
from nedra_calculate_polygons.exceptions import ContourFileNotAvailableError
from nedra_calculate_polygons.exceptions import ContourFileNotFoundError
from nedra_calculate_polygons.io import load_contour
from nedra_calculate_polygons.io import load_contour_from_external_format
from nedra_calculate_polygons.models.contour import Contour
from nedra_calculate_sdk.models import Messages
from shapely.geometry import Polygon
from creating_segment_calculation_module.border_clipping import clip_to_model_border
from creating_segment_calculation_module.constants import CALCULATION_NAME
from creating_segment_calculation_module.constants import BOUNDARY_TOUCH_AREA_TOLERANCE
from creating_segment_calculation_module.intersection_processing import check_intersections
from creating_segment_calculation_module.intersection_processing import process_intersections_rebuild
from creating_segment_calculation_module.models.creating_segments import CalculationInput
from creating_segment_calculation_module.models.creating_segments import CalculationResult
from creating_segment_calculation_module.models.creating_segments import FormationResult
from creating_segment_calculation_module.models.creating_segments import Line
from creating_segment_calculation_module.models.creating_segments import PolygonLine
from creating_segment_calculation_module.models.creating_segments import TargetPoint
from creating_segment_calculation_module.polygon_input_validation import remove_duplicate_lines_by_edges
from creating_segment_calculation_module.polygon_input_validation import validate_and_process_lines
from creating_segment_calculation_module.polygon_serialization import save_polygons_as_segments
from creating_segment_calculation_module.vertex_merging import merge_by_radius


logger = logging.getLogger('creating_segment_calculation_module')


CONTOUR_LOAD_ERRORS = (
    ContourFileNotAvailableError,
    ContourFileHasWrongSourceError,
    ContourFileNotFoundError,
    ContourFileFormatError,
)


def _build_result(
    formation: FormationResult | None,
    info_msgs: list[str],
    warning_msgs: list[str],
    error_msgs: list[str],
) -> CalculationResult:
    return CalculationResult(
        formation=formation,
        messages=Messages(
            info=info_msgs,
            warning=warning_msgs,
            error=error_msgs,
        ),
    )


def _convert_contour_to_polygon_line(contour: Contour) -> PolygonLine:
    lines: list[Line] = []

    for contour_line in contour.lines:
        points: list[TargetPoint] = []

        for point in contour_line.points:
            points.append(
                TargetPoint(
                    x=point.x,
                    y=point.y,
                )
            )

        lines.append(Line(points=points))

    return PolygonLine(lines=lines)

def _load_polygon_line(contour_file, contour_name: str) -> PolygonLine:
    try:
        contour = load_contour(contour_file, contour_name)
    except ContourFileFormatError:
        contour = load_contour_from_external_format(contour_file, contour_name)

    return _convert_contour_to_polygon_line(contour)

def _build_model_border(border_line: PolygonLine) -> Polygon | None:
    if not border_line.lines:
        return None

    border_points = []
    for point in border_line.lines[0].points:
        border_points.append((point.x, point.y))

    return Polygon(border_points)




def creating_segments(input_data: CalculationInput, storage) -> CalculationResult:
    """Основная функция создания сегментов."""
    info_msgs: list[str] = []
    warning_msgs: list[str] = []
    error_msgs: list[str] = []

    try:
        polygon_line = _load_polygon_line(
            input_data.polygon.value.file,
            input_data.polygon.name,
        )

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
                f"Все полилинии полигона '{input_data.polygon.name}' в параметре 'Внешний контур' "
                f"не прошли валидацию. Расчёт не выполнен.",
            )
            return _build_result(None, info_msgs, warning_msgs, error_msgs)

        model_border = None
        if input_data.formation_model and input_data.formation_model.border_model:
            try:
                border_line = _load_polygon_line(
                    input_data.formation_model.border_model.file,
                    'Контур модели',
                )
                model_border = _build_model_border(border_line)
            except CONTOUR_LOAD_ERRORS as exc:
                error_msgs.append(
                    f'{CALCULATION_NAME}'
                    f'Не удалось загрузить контур модели: {exc!s}. Контур модели не будет использован.',
                )

        polygons, clip_warnings = clip_to_model_border(polygons, model_border, input_data.polygon.name)
        warning_msgs.extend(clip_warnings)

        if not polygons:
            error_msgs.append(
                f"{CALCULATION_NAME}"
                f"Все полилинии полигона '{input_data.polygon.name}' исключены после обрезки по контуру модели. "
                f"Расчёт не выполнен.",
            )
            return _build_result(None, info_msgs, warning_msgs, error_msgs)

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
                f"Все полилинии полигона '{input_data.polygon.name}' исключены после склейки по радиусу. "
                f"Расчёт не выполнен.",
            )
            return _build_result(None, info_msgs, warning_msgs, error_msgs)

        if input_data.parameter.process_intersections == 0:
            polygons, intersection_warnings = check_intersections(polygons, input_data.polygon.name)
        else:
            polygons, intersection_warnings = process_intersections_rebuild(polygons, input_data.polygon.name)
        warning_msgs.extend(intersection_warnings)

        if not polygons:
            error_msgs.append(
                f"{CALCULATION_NAME}"
                f"Все полилинии полигона '{input_data.polygon.name}' исключены из-за пересечений. "
                f"Расчёт не выполнен.",
            )
            return _build_result(None, info_msgs, warning_msgs, error_msgs)


        segments = save_polygons_as_segments(polygons, input_data, storage)
        info_msgs.append(f'{CALCULATION_NAME}Успешно создано сегментов: {len(segments)}')

        formation = FormationResult(
            segment=segments,
            name=input_data.formation.name,
        )
        return _build_result(formation, info_msgs, warning_msgs, error_msgs)

    except CONTOUR_LOAD_ERRORS as exc:
        error_msgs.append(
            f'{CALCULATION_NAME}'
            f'Не удалось загрузить внешний контур: {exc!s}. Расчёт не выполнен.',
        )
        return _build_result(None, info_msgs, warning_msgs, error_msgs)

    except Exception as exc:
        import traceback

        error_msgs.append(
            f'{CALCULATION_NAME}'
            f'Неизвестная ошибка расчетного модуля: {exc!s}\n'
            f'Трассировка в логах воркера расчетного сервиса.',
        )
        logger.error(
            f'{CALCULATION_NAME}Неизвестная ошибка расчетного модуля: {exc!s}\n'
            f'Трассировка: {traceback.format_exc()}',
        )
        return _build_result(None, [], warning_msgs, error_msgs)
