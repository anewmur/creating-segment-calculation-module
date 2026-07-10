
from pathlib import Path
from creating_segment_calculation_module.models.creating_segments import CalculationInput


def build_input_data(polygon_path: Path, merge_radius: float = 0) -> CalculationInput:
    raw_input = {
        "parameter": {
            "name_by": "Имени полигона",
            "segments_group": "1",
            "segments_type": "2",
            "merge_radius": merge_radius,
            "process_intersections": 1,
        },
        "polygon": {
            "id": "12",
            "name": "Полигон",
            "value": {
                "file": {
                    "source": FileSource.LOCAL_FILE.value,
                    "path": str(polygon_path),
                },
            },
        },
        "formation": {
            "name": "пласт",
        },
    }
    return CalculationInput.model_validate(raw_input)

import json
import sys
from pathlib import Path

from shapely.geometry import Polygon as ShapelyPolygon

from creating_segment_calculation_module.entry_points.creating_segments import calculate
from creating_segment_calculation_module.models.creating_segments import CalculationInput
from creating_segment_calculation_module.prototype.polygon_visualizer import PolygonVisualizerSVG
from tests.utils import Storage


def load_polygons_from_json(path: Path) -> list[ShapelyPolygon]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    polygons = []
    for line in data["lines"]:
        coords = []
        for point in line["points"]:
            coords.append((point["x"], point["y"]))

        polygon = ShapelyPolygon(coords)
        if polygon.is_valid and not polygon.is_empty:
            polygons.append(polygon)

    return polygons


def load_polygons_from_result(result) -> list[ShapelyPolygon]:
    polygons = []

    if result.formation is None:
        return polygons

    for segment in result.formation.segment:
        segment_path = Path(segment.value.file.path)
        with segment_path.open(encoding="utf-8") as file:
            data = json.load(file)

        for line in data.get("lines", []):
            coords = []
            for point in line["points"]:
                coords.append((point["x"], point["y"]))

            polygon = ShapelyPolygon(coords)
            if polygon.is_valid and not polygon.is_empty:
                polygons.append(polygon)

    return polygons


def main(payload_path: Path, output_dir: Path) -> None:
    if not payload_path.exists():
        print(f"ОШИБКА: файл payload '{payload_path.resolve()}' не найден")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    with payload_path.open(encoding="utf-8") as payload_file:
        payload = json.load(payload_file)

    if "params" in payload:
        payload = payload["params"]

    if "input_data" in payload:
        payload = payload["input_data"]

    input_data = CalculationInput.model_validate(payload)
    polygon_path = Path(input_data.polygon.value.file.path)

    before = []
    if polygon_path.exists():
        before = load_polygons_from_json(polygon_path)
    else:
        print(f"ВНИМАНИЕ: файл полигона '{polygon_path.resolve()}' не найден")

    storage = Storage(base_dir=output_dir)
    result = calculate(input_data, storage=storage)

    after = load_polygons_from_result(result)

    if not after:
        print("ВНИМАНИЕ: расчёт не вернул ни одного сегмента")

    merge_radius = input_data.parameter.merge_radius

    visualizer = PolygonVisualizerSVG(merge_radius=merge_radius)
    visualizer.set_title("Полигоны")
    visualizer.draw_before_after(before, after, draw_vertices=True)

    output_path = output_dir / "result.html"
    visualizer.show(output_path)

    print(f"Info: {result.messages.info}")
    print(f"Warnings: {result.messages.warning}")
    print(f"Errors: {result.messages.error}")


if __name__ == "__main__":
    payload_file_name = "test.json"
    project_dir = Path(__file__).resolve().parents[2]
    data_dir = project_dir / "data"
    output_dir = project_dir / "output"

    if not data_dir.exists():
        print(f"ОШИБКА: директория '{data_dir.resolve()}' не найдена.")
        sys.exit(1)

    payload_path = data_dir / payload_file_name
    main(payload_path=payload_path, output_dir=output_dir)

