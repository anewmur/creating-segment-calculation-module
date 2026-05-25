from shapely.geometry import LineString
from shapely.geometry import Point
from shapely.geometry import Polygon

from .models.creating_segments import CalculationInput


def generate_combined_name(well_names: list[str], name_counter: dict[str, int]) -> str:
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
    well_names: list[str] = []
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
