import json
import logging
from pydantic import BaseModel, Field

# from nedra_calculate_ontology.ontology_model import File
# from nedra_calculate_sdk.calculation_module_services import Storage
from tests.viz_test.utils import File, Storage

from shapely.geometry import LineString
from shapely.geometry import Point
from shapely.geometry import Polygon

from .models.creating_segments import SEGMENT_TYPE_NAME_ENUM
from .models.creating_segments import CalculationInput
from .models.creating_segments import CalculationResult
from .models.creating_segments import FormationResult
from .models.creating_segments import Line
from .models.creating_segments import PolygonLine
from .models.creating_segments import PolygonValue
from .models.creating_segments import Segment
from .models.creating_segments import TargetPoint


CALCULATION_NAME = 'Расчёт сегментов\n'

logger = logging.getLogger('creating_segment_calculation_module')


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


def process_polygon_intersection(
    first_polygon: Polygon,
    second_polygon: Polygon,
    polygon_name: str,
) -> tuple[Polygon, Polygon, list[str]]:
    """Временная заглушка обработки пересечения двух полигонов."""
    warnings: list[str] = []
    return first_polygon, second_polygon, warnings


def check_intersections(polygons: list[Polygon], polygon_name: str) -> tuple[list[Polygon], list[str]]:
    """Проверяет полигоны на пересечения и последовательно обрабатывает пары."""
    warnings: list[str] = []

    for first_index in range(len(polygons)):
        for second_index in range(first_index + 1, len(polygons)):
            first_polygon = polygons[first_index]
            second_polygon = polygons[second_index]

            if not first_polygon.intersects(second_polygon):
                continue

            # Вычисляем область пересечения
            intersection = first_polygon.intersection(second_polygon)

            # Проверяем что пересечение имеет площадь (не только граница)
            if intersection.area <= 1e-5:
                continue


            # Изменяем прямо в цикле пересекающиеся полигоны. Да, опасно, но согласовано
            new_first_polygon, new_second_polygon, pair_warnings = process_polygon_intersection(
                first_polygon,
                second_polygon,
                polygon_name,
            )
            polygons[first_index] = new_first_polygon
            polygons[second_index] = new_second_polygon
            warnings.extend(pair_warnings)

    return polygons, warnings


def assign_segment_names(polygons: list[Polygon], input_data: CalculationInput, storage: Storage) -> list[Segment]:
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

        # Преобразование полигона в наш формат
        exterior = polygon.exterior
        points = [TargetPoint(x=coord[0], y=coord[1]) for coord in exterior.coords]
        line = Line(points=points)

        # Сохранение полигона в файл
        polygon_data = PolygonLine(lines=[line]).model_dump()
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


def creating_segments(input_data: CalculationInput, storage: Storage) -> CalculationResult:
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

        # Проверка пересечений
        polygons, intersection_warnings = check_intersections(polygons, input_data.polygon.name)
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
