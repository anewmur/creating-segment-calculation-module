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


def extract_points(geometry) -> list[Point]:
    """Возвращает только объекты типа Point из результата пересечения границ."""
    if geometry.is_empty:
        return []

    if geometry.geom_type == 'Point':
        return [geometry]

    if geometry.geom_type == 'MultiPoint':
        return list(geometry.geoms)

    result: list[Point] = []
    if hasattr(geometry, 'geoms'):
        for sub_geometry in geometry.geoms:
            if sub_geometry.geom_type == 'Point':
                result.append(sub_geometry)

    return result


def handle_containment(
    polygons: list[Polygon],
    first_index: int,
    second_index: int,
    warnings: list[str],
    polygon_name: str,
) -> None:
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
        return

    outer_polygon = polygons[outer_index]
    inner_polygon = polygons[inner_index]
    rebuilt_outer = outer_polygon.difference(inner_polygon)

    if (
        rebuilt_outer.is_empty
        or rebuilt_outer.geom_type != 'Polygon'
        or not rebuilt_outer.is_valid
        or len(rebuilt_outer.interiors) < 1
    ):
        warnings.append(
            f'{CALCULATION_NAME}'
            f'Полилиния полигона {polygon_name} исключена из расчёта из-за ошибки обработки вложенности.',
        )
        polygons.pop(outer_index)
        return

    polygons[outer_index] = rebuilt_outer


def process_intersections_rebuild(
    polygons: list[Polygon],
    polygon_name: str,
) -> tuple[list[Polygon], list[str]]:
    """
    Последовательно обрабатывает пары полигонов.
    В блоке 3 реализуется только случай вложенности без точек пересечения границ.
    """
    warnings: list[str] = []
    polygons = list(polygons)

    polygon_index = 0
    while polygon_index < len(polygons):
        other_index = polygon_index + 1
        while other_index < len(polygons):
            first_polygon = polygons[polygon_index]
            second_polygon = polygons[other_index]

            if not first_polygon.intersects(second_polygon):
                other_index += 1
                continue

            intersection_geom = first_polygon.intersection(second_polygon)
            if intersection_geom.is_empty or intersection_geom.area <= 0:
                other_index += 1
                continue

            boundary_intersection = first_polygon.boundary.intersection(second_polygon.boundary)
            intersection_points = extract_points(boundary_intersection)

            if len(intersection_points) == 0:
                before_len = len(polygons)
                handle_containment(
                    polygons=polygons,
                    first_index=polygon_index,
                    second_index=other_index,
                    warnings=warnings,
                    polygon_name=polygon_name,
                )
                if len(polygons) < before_len:
                    if other_index < polygon_index:
                        polygon_index -= 1
                        break
                    if other_index >= len(polygons):
                        break
                    continue

            # Ветки блока 4 и блока 5 здесь пока отсутствуют.
            other_index += 1
        polygon_index += 1

    return polygons, warnings


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

            # Проверяем что пересечение имеет площадь (не только граница)
            if intersection.area <= 1e-5:
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
