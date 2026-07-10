import json

from shapely.geometry import Polygon

from nedra_calculate_ontology.ontology_model import File
from .models.creating_segments import CalculationInput
from .models.creating_segments import Line
from .models.creating_segments import PolygonLine
from .models.creating_segments import PolygonValue
from .models.creating_segments import Segment
from .models.creating_segments import TargetPoint
from .models.creating_segments import SEGMENT_TYPE_NAME_ENUM
from .well_assignment import generate_combined_name
from .well_assignment import get_well_in_segment


def polygon_to_polygon_line(polygon: Polygon) -> PolygonLine:
    """Преобразует Shapely Polygon в PolygonLine с учётом внутренних контуров."""
    lines: list[Line] = []

    exterior_points = [TargetPoint(x=coord[0], y=coord[1]) for coord in polygon.exterior.coords]
    lines.append(Line(points=exterior_points))

    for interior in polygon.interiors:
        interior_points = [TargetPoint(x=coord[0], y=coord[1]) for coord in interior.coords]
        lines.append(Line(points=interior_points))

    return PolygonLine(lines=lines)

def build_polygon_segment_name(base_name: str, segment_index: int) -> str:
    """Формирует имя сегмента при именовании по исходному полигону.

    Первый сегмент получает имя исходного полигона.
    """
    if segment_index == 0:
        return base_name

    return f'{base_name} ({segment_index})'


def build_safe_segment_file_stem(name: str) -> str:
    """Формирует основу имени файла для сохранения сегментов."""
    safe_name = ""
    for char in name:
        if char.isalnum() or char in " _-":
            safe_name += char

    if not safe_name:
        return "segment"

    return safe_name

def save_polygon_as_segment_file(
    polygon: Polygon,
    file_path,
) -> None:
    """Сохраняет каждый рассчитанный полигон в json-файл для поля Segment.value."""
    polygon_line = polygon_to_polygon_line(polygon)
    content = json.dumps(polygon_line.model_dump(), ensure_ascii=False, indent=2)

    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)


def save_polygons_as_segments(
    polygons: list[Polygon],
    input_data: CalculationInput,
    storage,
) -> list[Segment]:
    """Создаёт список Segment: каждый рассчитанный полигон сохраняет в отдельный файл."""
    segments: list[Segment] = []
    base_name = input_data.polygon.name
    name_counter: dict[str, int] = {}

    for segment_index, polygon in enumerate(polygons):
        if input_data.parameter.name_by == SEGMENT_TYPE_NAME_ENUM.polygon_name:
            segment_name = build_polygon_segment_name(base_name, segment_index)
        elif input_data.parameter.name_by == SEGMENT_TYPE_NAME_ENUM.well_name:
            well_names = get_well_in_segment(input_data, polygon)
            segment_name = generate_combined_name(well_names, name_counter)
        else:
            raise ValueError(f'Неизвестный способ формирования имени сегмента: {input_data.parameter.name_by}')

        safe_name = build_safe_segment_file_stem(segment_name)
        file_path = storage.get_temp_dir() / f"{safe_name}_{input_data.parameter.segments_type}.json"

        save_polygon_as_segment_file(polygon, file_path)

        segment = Segment(
            group=input_data.parameter.segments_group,
            type=input_data.parameter.segments_type,
            name=segment_name,
            value=PolygonValue(file=File(path=str(file_path))),
            polygon_id=input_data.polygon.id,
        )
        segments.append(segment)

    return segments
