import json
import sys
from pathlib import Path
import webbrowser
from shapely.geometry import Polygon as ShapelyPolygon

from creating_segment_calculation_module.entry_points.creating_segments import calculate
from creating_segment_calculation_module.models.creating_segments import CalculationInput
from tests.utils import Storage
from prototype.polygon_visualizer_svg import PolygonVisualizerSVG


def load_polygons_from_json(path: Path) -> list[ShapelyPolygon]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = []
    for line in data["lines"]:
        coords = [(p["x"], p["y"]) for p in line["points"]]
        poly = ShapelyPolygon(coords)
        if poly.is_valid and not poly.is_empty:
            result.append(poly)
    return result


def load_polygons_from_result(result) -> list[ShapelyPolygon]:
    polygons: list[ShapelyPolygon] = []

    if result.formation is None:
        return polygons

    for segment in result.formation.segment:
        with open(segment.value.file.path, encoding="utf-8") as file:
            data = json.load(file)

        lines = data.get("lines", [])
        if not lines:
            continue

        shell = [(point["x"], point["y"]) for point in lines[0]["points"]]
        holes: list[list[tuple[float, float]]] = []

        for line in lines[1:]:
            hole = [(point["x"], point["y"]) for point in line["points"]]
            holes.append(hole)

        polygon = ShapelyPolygon(shell=shell, holes=holes)
        if polygon.is_valid and not polygon.is_empty:
            polygons.append(polygon)

    return polygons


def main(file, merge_radius) -> None:
    base_dir = Path(__file__).resolve().parents[1] / "data"
    output_dir = Path(__file__).resolve().parents[1] / "output"

    # Проверяем что всё на месте
    if not base_dir.exists():
        print(f"ОШИБКА: директория '{base_dir.resolve()}' не найдена. Создайте её и положите туда polygon2.json")
        sys.exit(1)

    polygon_path = base_dir / file
    if not polygon_path.exists():
        print(f"ОШИБКА: файл '{polygon_path.resolve()}' не найден")
        sys.exit(1)

    storage = Storage(base_dir=output_dir)

    payload = {
        "parameter": {
            "name_by": "Имени полигона",
            "segments_group": "1",
            "segments_type": "2",
            "merge_radius": merge_radius,
        },
        "polygon": {
            "id": "polygon",
            "name": "polygon2",
            "value": {"file": {"path": str(polygon_path)}},
        },
        "formation": {"name": "Пласт 1"},
        "well": [],
    }

    # До расчёта
    before = load_polygons_from_json(polygon_path)
    if not before:
        print(f"ОШИБКА: в '{polygon_path}' нет валидных полигонов")
        sys.exit(1)

    # Расчёт
    input_data = CalculationInput.model_validate(payload)
    result = calculate(input_data, storage=storage)

    # После расчёта
    after = load_polygons_from_result(result)

    if not after:
        print("ВНИМАНИЕ: расчёт не вернул ни одного сегмента")

    # Визуализация
    viz = PolygonVisualizerSVG(merge_radius=input_data.parameter.merge_radius)
    viz.set_title("Полигоны")
    viz.draw_before_after(before, after, draw_vertices=True)

    output_path = output_dir / "result.html"

    viz.show(output_path)

    print(f"Визуализация: {output_path.resolve()}")

    # Логи
    print("Info:", result.info)
    print("Warnings:", result.warning)
    print("Errors:", result.error)


if __name__ == "__main__":
    # file = "polygon2.json"
    # file = "polygon2_a.json"
    # file = "polygon2_b.json"
    # file = "polygon2_c.json"
    file = "polygon2_d.json"
    # file = "test_nested_polygon.json"
    # file = "test_intersection_poligon_many_points_1.json"
    # file = "test_intersection_poligon_many_points_2.json"

    merge_radius=10
    main(file=file, merge_radius=merge_radius)