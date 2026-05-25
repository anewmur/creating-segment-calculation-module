from shapely.geometry import Polygon

from .constants import CALCULATION_NAME
from .models.creating_segments import Line
from .models.creating_segments import PolygonLine
from .models.creating_segments import TargetPoint


def _point_key(point: TargetPoint) -> tuple[float, float]:
    return point.x, point.y


def _edge_key(
    first_point: TargetPoint,
    second_point: TargetPoint,
) -> tuple[tuple[float, float], tuple[float, float]]:
    first_key = _point_key(first_point)
    second_key = _point_key(second_point)
    if first_key <= second_key:
        return first_key, second_key
    return second_key, first_key


def _line_edges_key(line: Line) -> frozenset[tuple[tuple[float, float], tuple[float, float]]]:
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for point_index in range(len(line.points) - 1):
        first_point = line.points[point_index]
        second_point = line.points[point_index + 1]
        edges.append(_edge_key(first_point, second_point))

    return frozenset(edges)


def remove_duplicate_lines_by_edges(polygon_line: PolygonLine, polygon_name: str) -> tuple[PolygonLine, list[str]]:
    unique_lines: list[Line] = []
    seen_line_keys: set[frozenset[tuple[tuple[float, float], tuple[float, float]]]] = set()
    warning_messages: list[str] = []
    removed_lines_count = 0
    removed_lines_indices: list[int] = []

    for line_index, line in enumerate(polygon_line.lines):
        if len(line.points) < 2:
            unique_lines.append(line)
            continue

        first_point = line.points[0]
        last_point = line.points[-1]
        if (first_point.x != last_point.x) or (first_point.y != last_point.y):
            unique_lines.append(line)
            continue

        line_key = _line_edges_key(line)
        if line_key in seen_line_keys:
            removed_lines_count += 1
            removed_lines_indices.append(line_index + 1)
            continue

        seen_line_keys.add(line_key)
        unique_lines.append(line)

    if removed_lines_count > 0:
        removed_indices = ', '.join(str(line_index) for line_index in removed_lines_indices)
        warning_messages.append(
            f'{CALCULATION_NAME}'
            f'Полигон {polygon_name} содержит повторяющиеся замкнутые полилинии: '
            f'удалено {removed_lines_count} шт. (индексы: {removed_indices}).',
        )

    return PolygonLine(lines=unique_lines), warning_messages


def validate_and_process_lines(polygon_line: PolygonLine, polygon_name: str) -> tuple[list[Polygon], list[str]]:
    """Проверяет линии на валидность и преобразует в полигоны"""
    valid_polygons: list[Polygon] = []
    warnings: list[str] = []

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
