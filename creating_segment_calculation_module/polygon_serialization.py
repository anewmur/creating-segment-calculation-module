import json

from shapely.geometry import Polygon

from .models.creating_segment import File
from .models.creating_segments import CalculationInput
from .models.creating_segments import Line
from .models.creating_segments import PolygonLine
from .models.creating_segments import PolygonValue
from .models.creating_segments import Segment
from .models.creating_segments import TargetPoint


def polygon_to_polygon_line(polygon: Polygon) -> PolygonLine:
    """Преобразует Shapely Polygon в PolygonLine с учётом внутренних контуров."""
    lines: list[Line] = []

    exterior_points = [TargetPoint(x=coord[0], y=coord[1]) for coord in polygon.exterior.coords]
    lines.append(Line(points=exterior_points))

    for interior in polygon.interiors:
        interior_points = [TargetPoint(x=coord[0], y=coord[1]) for coord in interior.coords]
        lines.append(Line(points=interior_points))

    return PolygonLine(lines=lines)


def save_polygons_as_single_segment(
    polygons: list[Polygon],
    input_data: CalculationInput,
    storage,
) -> list[Segment]:
    """Сохраняет все полигоны в один json-файл формата входных данных."""
    all_lines: list[dict[str, object]] = []

    for polygon in polygons:
        polygon_line = polygon_to_polygon_line(polygon)
        polygon_data = polygon_line.model_dump()
        polygon_lines = polygon_data["lines"]
        all_lines.extend(polygon_lines)

    content = json.dumps({"lines": all_lines}, ensure_ascii=False, indent=2)

    base_name = input_data.polygon.name
    safe_name = "".join(char for char in base_name if char.isalnum() or char in " _-")
    if not safe_name:
        safe_name = "segments"

    file_path = storage.get_temp_dir() / f"{safe_name}_{input_data.parameter.segments_type}.json"

    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

    segment = Segment(
        group=input_data.parameter.segments_group,
        type=input_data.parameter.segments_type,
        name=base_name,
        value=PolygonValue(file=File(path=str(file_path))),
        polygon_id=input_data.polygon.id,
    )
    return [segment]
