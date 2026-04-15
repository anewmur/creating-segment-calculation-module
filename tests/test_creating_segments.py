import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from shapely.geometry import Polygon
from creating_segment_calculation_module.creating_segments import check_intersections
from creating_segment_calculation_module.creating_segments import creating_segments
from creating_segment_calculation_module.models.creating_segments import CalculationInput
from tests.viz_test.utils import Storage


def test_creating_segments_with_border():
    # Интеграционный тест: обрезка по границе модели и сохранение результата.
    with TemporaryDirectory(prefix='test_creating_segment') as base_dir:
        border = """{"lines":[{"points":[{"x":0,"y":0},{"x":0,"y":1000},
        {"x":1000,"y":1000},{"x":1000,"y":0}]}]}
        """
        base_dir = Path(base_dir)
        border_path = base_dir / 'border'
        border_path.write_text(border, encoding='utf-8')

        polygon = """{"lines":[{"points":[{"x":0,"y":0},{"x":0,"y":500},
        {"x":500,"y":500},{"x":500,"y":0}, {"x":0,"y":0}]},
        {"points":[{"x":-10,"y":-20},{"x":-10,"y":-500},
        {"x":-400,"y":-500},{"x":-500,"y":-50},{"x":-10,"y":-20} ]}]}
        """
        polygon_path = base_dir / 'polygon'
        polygon_path.write_text(polygon, encoding='utf-8')

        storage = Storage(base_dir=base_dir)
        input_data = {
            'parameter': {'name_by': 'Имени полигона', 'segments_group': '1', 'segments_type': '2'},
            'polygon': {'id': '12', 'name': 'Полигон', 'value': {'file': {'path': str(polygon_path)}}},
            'formation': {'name': 'пласт'},
            'formation_model': {'border_model': {'file': {'path': str(border_path)}}},
        }

        input_data = CalculationInput.model_validate(input_data)

        result = creating_segments(input_data, storage)

        with open(result.formation.segment[0].value.file.path, 'rb') as file:
            data = json.load(file)

        assert result.info == ['Расчёт сегментов\nУспешно создано сегментов: 1']
        assert result.warning == [
            'Расчёт сегментов\n'
            'Полигон Полигон в параметре Полигоны не входит в границы модели пласта, '
            'расчёт будет продолжен без её учёта.',
        ]
        assert result.error == []
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
            ],
        }

@pytest.mark.xfail(reason="Обработка пересечений ещё не реализована: process_polygon_intersection возвращает полигоны без изменений")
def test_check_intersections_excludes_overlapping_polygons():
    polygon_1 = Polygon([(0, 0), (0, 500), (500, 500), (500, 0), (0, 0)])
    polygon_2 = Polygon([(250, 0), (250, 500), (750, 500), (750, 0), (250, 0)])

    result_polygons, warnings = check_intersections([polygon_1, polygon_2], 'Полигон')

    assert result_polygons == []
    assert warnings == [
        'Расчёт сегментов\n'
        'Полилинии полигона Полигон в параметре Полигоны пересекаются между собой, '
        'расчёт будет продолжен без её (их) учёта.',
    ]


def test_creating_segments_with_well():
    # Тест основной функции.
    with TemporaryDirectory(prefix='test_creating_segment') as base_dir:
        polygon = """{"lines":[{"points":[{"x":0,"y":0},{"x":0,"y":500},
        {"x":500,"y":500},{"x":500,"y":0}, {"x":0,"y":0}]}]}
        """
        base_dir = Path(base_dir)
        polygon_path = base_dir / 'polygon1'
        polygon_path.write_text(polygon, encoding='utf-8')

        storage = Storage(base_dir=base_dir)
        input_data = {
            'parameter': {'name_by': 'Имени ствола', 'segments_group': '1', 'segments_type': '2'},
            'polygon': {'id': '12', 'name': 'Полигон', 'value': {'file': {'path': str(polygon_path)}}},
            'formation': {'name': 'пласт'},
            'well': [
                {'name': 'well1', 'target': {'point': [{'x': 10, 'y': 10}]}},
                {'name': 'well2', 'target': {'point': [{'x': -10, 'y': -10}]}},
            ],
        }

        input_data = CalculationInput.model_validate(input_data)

        result = creating_segments(input_data, storage)
        assert result.info == ['Расчёт сегментов\nУспешно создано сегментов: 1']
        assert result.formation.segment[0].name == 'well1'


def test_parameter_defaults():
    """Вход без новых полей — подставляются значения по умолчанию."""
    raw = {
        'parameter': {'name_by': 'Имени полигона', 'segments_group': '1', 'segments_type': '2'},
        'polygon': {'id': '1', 'name': 'test', 'value': {'file': {'path': '/tmp/test'}}},
        'formation': {'name': 'пласт'},
    }
    data = CalculationInput.model_validate(raw)
    assert data.parameter.merge_radius == 20
    assert data.parameter.process_intersections == 1


def test_parameter_explicit_values():
    """Вход с явно заданными значениями."""
    raw = {
        'parameter': {
            'name_by': 'Имени полигона',
            'segments_group': '1',
            'segments_type': '2',
            'merge_radius': 7,
            'process_intersections': 0,
        },
        'polygon': {'id': '1', 'name': 'test', 'value': {'file': {'path': '/tmp/test'}}},
        'formation': {'name': 'пласт'},
    }
    data = CalculationInput.model_validate(raw)
    assert data.parameter.merge_radius == 7
    assert data.parameter.process_intersections == 0
