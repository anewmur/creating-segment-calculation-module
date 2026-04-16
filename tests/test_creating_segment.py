import json
from pathlib import Path
from tempfile import TemporaryDirectory

from creating_segment_calculation_module.old_creating_segment import old_creating_segment
from creating_segment_calculation_module.models.creating_segment import CalculationInput
from creating_segment_calculation_module.models.creating_segment import Parameter
from creating_segment_calculation_module.models.creating_segment import Polygon
from creating_segment_calculation_module.models.creating_segment import PolygonValue
from creating_segment_calculation_module.models.creating_segment import SegmentParameters
from creating_segment_calculation_module.models.creating_segment import SegmentType
from nedra_calculate_ontology.ontology_model import File
from nedra_calculate_sdk.calculation_module_services import Storage


def test_creating_segment():
    # Тест основной функции.
    with TemporaryDirectory(prefix='test_creating_segment') as base_dir:
        border = """{"lines":[{"points":[{"x":0,"y":0},{"x":0,"y":1000},
        {"x":1000,"y":1000},{"x":1000,"y":0}]}]}
        """
        base_dir = Path(base_dir)
        border_path = base_dir / 'border'
        border_path.write_text(border, encoding='utf-8')

        polygon1 = """{"lines":[{"points":[{"x":0,"y":0},{"x":0,"y":500},
        {"x":500,"y":500},{"x":500,"y":0}, {"x":0,"y":0}]}]}
        """
        polygon1_path = base_dir / 'polygon1'
        polygon1_path.write_text(polygon1, encoding='utf-8')

        polygon2 = """{"lines":[{"points":[{"x":0,"y":0},{"x":0,"y":500},
        {"x":400,"y":500},{"x":500,"y":0} , {"x":0,"y":0}]}]}
        """
        polygon2_path = base_dir / 'polygon2'
        polygon2_path.write_text(polygon2, encoding='utf-8')

        storage = Storage(base_dir=base_dir)

        input_data = CalculationInput(
            parameter=Parameter(
                segment=SegmentParameters(
                    unite=True,
                    segment_name='well',
                    segment_type=SegmentType.general.value,
                    border_model=PolygonValue(file=File(path=str(border_path))),
                ),
            ),
            polygon=[
                Polygon(value=PolygonValue(file=File(path=str(polygon1_path)))),
                Polygon(value=PolygonValue(file=File(path=str(polygon2_path)))),
            ],
        )

        result = creating_segment(input_data, storage)
        with open(result.polygon[0].value.file.path, 'rb') as f:
            data = json.load(f)

        assert data == {
            'lines': [
                {
                    'points': [
                        {'x': 0.0, 'y': 0.0},
                        {'x': 0.0, 'y': 500.0},
                        {'x': 500.0, 'y': 500.0},
                        {'x': 500.0, 'y': 0.0},
                        {'x': 0.0, 'y': 0.0},
                    ],
                },
                {
                    'points': [
                        {'x': 0.0, 'y': 0.0},
                        {'x': 0.0, 'y': 500.0},
                        {'x': 400.0, 'y': 500.0},
                        {'x': 500.0, 'y': 0.0},
                        {'x': 0.0, 'y': 0.0},
                    ],
                },
            ],
        }

        input_data = CalculationInput(
            parameter=Parameter(
                segment=SegmentParameters(
                    unite=False,
                    segment_name='well',
                    segment_type=SegmentType.general.value,
                    border_model=PolygonValue(file=File(path=str(border_path))),
                ),
            ),
            polygon=[
                Polygon(value=PolygonValue(file=File(path=str(polygon1_path)))),
                Polygon(value=PolygonValue(file=File(path=str(polygon2_path)))),
            ],
        )

        result = creating_segment(input_data, storage)
        with open(result.polygon[0].value.file.path, 'rb') as f:
            data = json.load(f)

        assert data == {
            'lines': [
                {
                    'points': [
                        {'x': 0.0, 'y': 0.0},
                        {'x': 0.0, 'y': 500.0},
                        {'x': 400.0, 'y': 500.0},
                        {'x': 500.0, 'y': 0.0},
                        {'x': 0.0, 'y': 0.0},
                    ],
                },
            ],
        }
        with open(result.polygon[1].value.file.path, 'rb') as f:
            data = json.load(f)

        assert data == {
            'lines': [
                {
                    'points': [
                        {'x': 0.0, 'y': 0.0},
                        {'x': 0.0, 'y': 500.0},
                        {'x': 400.0, 'y': 500.0},
                        {'x': 500.0, 'y': 0.0},
                        {'x': 0.0, 'y': 0.0},
                    ],
                },
            ],
        }

        polygon2 = """{"lines":[{"points":[{"x":-10,"y":-20},{"x":-10,"y":-500},
        {"x":-400,"y":-500},{"x":-500,"y":-50},{"x":-10,"y":-20} ]}]}
        """
        polygon2_path = base_dir / 'polygon2'
        polygon2_path.write_text(polygon2, encoding='utf-8')

        input_data = CalculationInput(
            parameter=Parameter(
                segment=SegmentParameters(
                    unite=False,
                    segment_name='well',
                    segment_type=SegmentType.general.value,
                    border_model=PolygonValue(file=File(path=str(border_path))),
                ),
            ),
            polygon=[
                Polygon(value=PolygonValue(file=File(path=str(polygon1_path)))),
                Polygon(value=PolygonValue(file=File(path=str(polygon2_path)))),
            ],
        )

        try:
            creating_segment(input_data, storage)
        except Exception as ex:
            assert str(ex) == 'Не попадают в контур: Полигон 2'
