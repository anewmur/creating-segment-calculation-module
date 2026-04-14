import json
import sys
from pathlib import Path
import webbrowser
from shapely.geometry import Polygon as ShapelyPolygon

from creating_segment_calculation_module.entry_points.creating_segments import calculate
from creating_segment_calculation_module.models.creating_segments import CalculationInput
from tests.viz_test.utils import Storage
from tests.viz_test.polygon_visualizer_svg import PolygonVisualizerSVG


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
    polygons = []
    if result.formation is None:
        return polygons
    for segment in result.formation.segment:
        with open(segment.value.file.path, encoding="utf-8") as f:
            data = json.load(f)
        for line in data["lines"]:
            coords = [(p["x"], p["y"]) for p in line["points"]]
            poly = ShapelyPolygon(coords)
            if poly.is_valid and not poly.is_empty:
                polygons.append(poly)
    return polygons


def main() -> None:
    base_dir = Path(__file__).resolve().parents[2] / "data"

    # Проверяем что всё на месте
    if not base_dir.exists():
        print(f"ОШИБКА: директория '{base_dir.resolve()}' не найдена. Создайте её и положите туда polygon2.json")
        sys.exit(1)

    polygon_path = base_dir / "polygon2.json"
    if not polygon_path.exists():
        print(f"ОШИБКА: файл '{polygon_path.resolve()}' не найден")
        sys.exit(1)

    storage = Storage(base_dir=base_dir)

    payload = {
        "parameter": {
            "name_by": "Имени полигона",
            "segments_group": "1",
            "segments_type": "2",
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
    viz = PolygonVisualizerSVG()
    viz.set_title("Сегменты: до и после")
    viz.draw_before_after(before, after, draw_vertices=True)

    output_path = base_dir / "result.html"

    viz.show(base_dir / "result.html")

    print(f"Визуализация: {output_path.resolve()}")

    # Логи
    print("Info:", result.info)
    print("Warnings:", result.warning)
    print("Errors:", result.error)




if __name__ == "__main__":
    main()
