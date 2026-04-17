import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from shapely.geometry import GeometryCollection
from shapely.geometry import LineString
from shapely.geometry import MultiPoint
from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.ops import unary_union

from creating_segment_calculation_module.creating_segments import check_intersections
from creating_segment_calculation_module.creating_segments import BOUNDARY_TOUCH_AREA_TOLERANCE
from creating_segment_calculation_module.creating_segments import ContainmentHandlingStatus
from creating_segment_calculation_module.creating_segments import ManyPointsRebuildStatus
from creating_segment_calculation_module.creating_segments import PERIMETER_AREA_THRESHOLD
from creating_segment_calculation_module.creating_segments import TwoPointsRebuildStatus
from creating_segment_calculation_module.creating_segments import creating_segments
from creating_segment_calculation_module.creating_segments import extract_points
from creating_segment_calculation_module.creating_segments import handle_containment
from creating_segment_calculation_module.creating_segments import handle_many_points_intersection
from creating_segment_calculation_module.creating_segments import handle_two_points_intersection
from creating_segment_calculation_module.creating_segments import polygon_to_polygon_line
from creating_segment_calculation_module.creating_segments import process_intersections_rebuild
from creating_segment_calculation_module.models.creating_segments import CalculationInput

from tests.utils import Storage


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


def test_check_intersections_ignores_tiny_numerical_overlap():
    polygon_1 = Polygon([(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)])
    polygon_2 = Polygon([(9.9999995, 0), (9.9999995, 10), (20, 10), (20, 0), (9.9999995, 0)])

    result_polygons, warnings = check_intersections([polygon_1, polygon_2], 'Полигон')

    assert len(result_polygons) == 2
    assert warnings == []


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


def test_handle_containment_rebuilds_outer_and_keeps_inner():
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])

    polygons = [outer, inner]
    containment_result = handle_containment(
        polygons=polygons,
        first_index=0,
        second_index=1,
    )

    assert containment_result.status == ContainmentHandlingStatus.rebuilt
    assert containment_result.outer_index == 0
    assert len(polygons) == 2
    assert abs(polygons[1].area - inner.area) < 1e-9
    assert abs(polygons[0].area - (outer.area - inner.area)) < 1e-9
    assert len(polygons[0].interiors) == 1


def test_handle_containment_returns_exclude_outer_on_rebuild_failure(monkeypatch):
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])
    polygons = [outer, inner]

    def fake_rebuild_outer_polygon_for_containment(outer_polygon, inner_polygon):
        return Polygon()

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments._rebuild_outer_polygon_for_containment',
        fake_rebuild_outer_polygon_for_containment,
    )

    containment_result = handle_containment(
        polygons=polygons,
        first_index=0,
        second_index=1,
    )

    assert containment_result.status == ContainmentHandlingStatus.exclude_outer
    assert containment_result.outer_index == 0
    assert polygons[0].equals(outer)
    assert polygons[1].equals(inner)
    assert len(polygons[1].interiors) == 0


def test_handle_containment_not_containment_does_not_mutate_polygons():
    polygon_1 = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    polygon_2 = Polygon([(150, 0), (250, 0), (250, 100), (150, 100)])
    polygons = [polygon_1, polygon_2]
    original_polygons = [polygon for polygon in polygons]

    containment_result = handle_containment(
        polygons=polygons,
        first_index=0,
        second_index=1,
    )

    assert containment_result.status == ContainmentHandlingStatus.not_containment
    assert containment_result.outer_index is None
    assert len(polygons) == len(original_polygons)
    assert all(new.equals(old) for new, old in zip(polygons, original_polygons, strict=True))


def test_handle_containment_not_containment_with_overlap_does_not_mutate_polygons():
    polygon_1 = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    polygon_2 = Polygon([(50, -10), (150, -10), (150, 60), (50, 60)])
    polygons = [polygon_1, polygon_2]
    original_polygons = [polygon for polygon in polygons]

    containment_result = handle_containment(
        polygons=polygons,
        first_index=0,
        second_index=1,
    )

    assert containment_result.status == ContainmentHandlingStatus.not_containment
    assert containment_result.outer_index is None
    assert all(new.equals(old) for new, old in zip(polygons, original_polygons, strict=True))


def test_process_intersections_rebuild_containment_case():
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])

    result, warnings = process_intersections_rebuild([outer, inner], 'test')

    assert len(result) == 2
    assert len(warnings) == 0

    rebuilt_outer = next(polygon for polygon in result if len(polygon.interiors) == 1)
    preserved_inner = next(polygon for polygon in result if len(polygon.interiors) == 0)

    assert len(rebuilt_outer.interiors) == 1
    assert abs(preserved_inner.area - inner.area) < 1e-9
    assert rebuilt_outer.intersection(preserved_inner).area < 1e-9


def test_process_intersections_rebuild_excludes_unsupported_overlap():
    polygon_1 = Polygon([(0, 0), (0, 500), (500, 500), (500, 0), (0, 0)])
    polygon_2 = Polygon([(250, 0), (250, 500), (750, 500), (750, 0), (250, 0)])

    result, warnings = process_intersections_rebuild([polygon_1, polygon_2], 'Полигон')

    assert result == []
    assert len(warnings) == 1
    assert 'до реализации блоков 4 и 5' in warnings[0]


def test_two_points_branch_zero_overlap_after_rebuild():
    square_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    square_b = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])

    result, warnings = process_intersections_rebuild([square_a, square_b], 'test')

    assert len(result) == 2
    assert warnings == []
    assert result[0].intersection(result[1]).area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_two_points_branch_has_shared_edge():
    square_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    square_b = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])

    result, _ = process_intersections_rebuild([square_a, square_b], 'test')

    shared_boundary = result[0].boundary.intersection(result[1].boundary)
    assert shared_boundary.length > 0


def test_two_points_branch_preserves_total_area():
    square_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    square_b = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])
    original_union_area = square_a.union(square_b).area

    result, _ = process_intersections_rebuild([square_a, square_b], 'test')

    rebuilt_area = sum(polygon.area for polygon in result)
    assert abs(rebuilt_area - original_union_area) < 1e-6 * original_union_area


def test_two_points_branch_splits_overlap_evenly_for_symmetric_case():
    square_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    square_b = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])

    only_a_area = square_a.difference(square_b).area
    only_b_area = square_b.difference(square_a).area
    overlap_area = square_a.intersection(square_b).area
    expected_area = only_a_area + overlap_area / 2

    result, _ = process_intersections_rebuild([square_a, square_b], 'test')

    assert len(result) == 2
    assert abs(result[0].area - expected_area) < 1e-6 * expected_area
    assert abs(result[1].area - expected_area) < 1e-6 * expected_area
    assert abs(only_b_area - only_a_area) < 1e-9


def test_two_points_branch_assigns_overlap_halves_to_original_indexes():
    polygon_a = Polygon([(0, 0), (12, 0), (12, 10), (0, 10)])
    polygon_b = Polygon([(6, 2), (14, 2), (14, 12), (6, 12)])

    result, warnings = process_intersections_rebuild([polygon_a, polygon_b], 'test')

    only_a = polygon_a.difference(polygon_b)
    only_b = polygon_b.difference(polygon_a)

    assert warnings == []
    assert result[0].intersection(only_a).area >= only_a.area - BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[1].intersection(only_b).area >= only_b.area - BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[0].intersection(only_b).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[1].intersection(only_a).area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_two_points_branch_sequential_processing_clears_all_overlaps():
    polygon_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    polygon_b = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])
    polygon_c = Polygon([(-5, 5), (5, 5), (5, 15), (-5, 15)])

    result, warnings = process_intersections_rebuild([polygon_a, polygon_b, polygon_c], 'test')

    assert len(result) == 3
    assert warnings == []

    for first_index in range(len(result)):
        for second_index in range(first_index + 1, len(result)):
            overlap_area = result[first_index].intersection(result[second_index]).area
            assert overlap_area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_handle_two_points_intersection_returns_rebuilt_and_mutates_list():
    square_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    square_b = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])
    polygons = [square_a, square_b]

    outcome = handle_two_points_intersection(
        polygons=polygons,
        first_index=0,
        second_index=1,
        first_intersection_point=Point(10, 5),
        second_intersection_point=Point(5, 10),
    )

    assert outcome.status == TwoPointsRebuildStatus.rebuilt
    assert polygons[0] is not square_a
    assert polygons[1] is not square_b
    assert polygons[0].intersection(polygons[1]).area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_two_points_branch_is_not_used_when_boundaries_share_segment():
    polygon_1 = Polygon([(0, 0), (0, 500), (500, 500), (500, 0), (0, 0)])
    polygon_2 = Polygon([(250, 0), (250, 500), (750, 500), (750, 0), (250, 0)])

    result, warnings = process_intersections_rebuild([polygon_1, polygon_2], 'test')

    assert result == []
    assert len(warnings) == 1
    assert 'неподдерживаемым способом' in warnings[0]


def test_two_points_entry_guard_uses_shared_segment_check(monkeypatch):
    polygon_1 = Polygon([(0, 0), (0, 8), (8, 8), (8, 0), (0, 0)])
    polygon_2 = Polygon([(4, -1), (4, 9), (12, 9), (12, -1), (4, -1)])

    def fake_extract_points(boundary_intersection):
        return [Point(8, 0), Point(8, 8)]

    def fake_handle_two_points_intersection(polygons, first_index, second_index, first_intersection_point, second_intersection_point):
        raise AssertionError('two points branch should not be called when shared segment exists')

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments.extract_points',
        fake_extract_points,
    )
    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments._has_boundary_shared_segment',
        lambda boundary_intersection: True,
    )
    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments.handle_two_points_intersection',
        fake_handle_two_points_intersection,
    )

    result, warnings = process_intersections_rebuild([polygon_1, polygon_2], 'test')

    assert result == []
    assert len(warnings) == 1
    assert 'неподдерживаемым способом' in warnings[0]

def test_two_points_branch_excludes_both_polygons_when_rebuild_failed(monkeypatch):
    polygon_1 = Polygon([(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)])
    polygon_2 = Polygon([(5, 5), (5, 15), (15, 15), (15, 5), (5, 5)])

    class FakeTwoPointsResult:
        status = TwoPointsRebuildStatus.rebuild_failed

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments.handle_two_points_intersection',
        lambda polygons, first_index, second_index, first_intersection_point,
               second_intersection_point: FakeTwoPointsResult(),
    )

    result, warnings = process_intersections_rebuild([polygon_1, polygon_2], 'test')

    assert result == []
    assert warnings == [
        'Расчёт сегментов\n'
        'Полилинии полигона test с пересечением в 2 точках '
        'не удалось перестроить, обе полилинии исключены из расчёта.',
    ]


def test_two_points_branch_keeps_boundary_polygon_and_rebuilds_other():
    polygon_left = Polygon([(0, 0), (0, 10), (8, 10), (8, 0), (0, 0)])
    polygon_right = Polygon([(6, -2), (6, 14), (16, 14), (16, -2), (6, -2)])

    result, warnings = process_intersections_rebuild([polygon_left, polygon_right], 'test')

    # cut_segment = (6,0)-(6,10) лежит на левой грани polygon_right,
    # значит правый (index=1) фиксируется, левый (index=0) перестраивается.
    expected_left = polygon_left.difference(polygon_right)

    assert len(result) == 2
    assert warnings == []
    assert result[0].symmetric_difference(expected_left).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[1].symmetric_difference(polygon_right).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[0].intersection(result[1]).area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_handle_two_points_intersection_keeps_fixed_boundary_polygon_and_rebuilds_other():
    polygon_left = Polygon([(0, 0), (0, 10), (8, 10), (8, 0), (0, 0)])
    polygon_right = Polygon([(6, -2), (6, 14), (16, 14), (16, -2), (6, -2)])
    polygons = [polygon_left, polygon_right]

    # Реальные точки пересечения границ для этой пары — (6,0) и (6,10),
    # а не (8,0)/(8,10) как было раньше.
    outcome = handle_two_points_intersection(
        polygons=polygons,
        first_index=0,
        second_index=1,
        first_intersection_point=Point(6, 0),
        second_intersection_point=Point(6, 10),
    )

    expected_left = polygon_left.difference(polygon_right)

    assert outcome.status == TwoPointsRebuildStatus.rebuilt
    assert polygons[0].symmetric_difference(expected_left).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert polygons[1].symmetric_difference(polygon_right).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert polygons[0].intersection(polygons[1]).area <= BOUNDARY_TOUCH_AREA_TOLERANCE

def test_process_intersections_rebuild_ignores_tiny_numerical_overlap():
    polygon_1 = Polygon([(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)])
    polygon_2 = Polygon([(9.9999995, 0), (9.9999995, 10), (20, 10), (20, 0), (9.9999995, 0)])

    result, warnings = process_intersections_rebuild([polygon_1, polygon_2], 'Полигон')

    assert len(result) == 2
    assert warnings == []


def test_process_intersections_rebuild_excludes_outer_when_containment_rebuild_fails(monkeypatch):
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])

    def fake_rebuild_outer_polygon_for_containment(outer_polygon, inner_polygon):
        return Polygon()

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments._rebuild_outer_polygon_for_containment',
        fake_rebuild_outer_polygon_for_containment,
    )

    result, warnings = process_intersections_rebuild([outer, inner], 'test')

    assert len(result) == 1
    assert abs(result[0].area - inner.area) < 1e-9
    assert len(warnings) == 1
    assert 'ошибки обработки вложенности' in warnings[0]


def test_process_intersections_rebuild_excludes_outer_when_containment_rebuild_returns_non_polygon(monkeypatch):
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])

    def fake_rebuild_outer_polygon_for_containment(outer_polygon, inner_polygon):
        return LineString([(0, 0), (10, 10)])

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments._rebuild_outer_polygon_for_containment',
        fake_rebuild_outer_polygon_for_containment,
    )

    result, warnings = process_intersections_rebuild([outer, inner], 'test')

    assert len(result) == 1
    assert abs(result[0].area - inner.area) < 1e-9
    assert len(warnings) == 1


def test_process_intersections_rebuild_excludes_outer_when_containment_rebuild_returns_invalid_polygon(monkeypatch):
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])

    def fake_rebuild_outer_polygon_for_containment(outer_polygon, inner_polygon):
        return Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments._rebuild_outer_polygon_for_containment',
        fake_rebuild_outer_polygon_for_containment,
    )

    result, warnings = process_intersections_rebuild([outer, inner], 'test')

    assert len(result) == 1
    assert abs(result[0].area - inner.area) < 1e-9
    assert len(warnings) == 1


def test_many_points_branch_zero_overlap_after_rebuild():
    base = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    zigzag = Polygon(
        [
            (80, 10), (120, 10), (120, 20), (80, 20),
            (120, 40), (80, 40), (120, 60), (80, 60),
            (120, 80), (80, 80), (120, 90), (80, 90),
        ],
    )

    result, warnings = process_intersections_rebuild([base, zigzag], 'test')

    assert warnings == []
    for first_index in range(len(result)):
        for second_index in range(first_index + 1, len(result)):
            overlap_area = result[first_index].intersection(result[second_index]).area
            assert overlap_area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_many_points_branch_preserves_all_valid_fragments():
    polygon_a = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    polygon_b = Polygon(
        [
            (20, -10), (40, -10), (40, 30), (60, 30), (60, -10), (80, -10),
            (80, 110), (60, 110), (60, 70), (40, 70), (40, 110), (20, 110),
        ],
    )

    result, warnings = process_intersections_rebuild([polygon_a, polygon_b], 'test')

    assert warnings == []
    # Для этой пары keeper — polygon_a, а loser (polygon_b) после difference
    # должен распасться на два валидных фрагмента (сверху и снизу).
    # Итого ожидаем ровно 3 полигона: 1 keeper + 2 loser fragments.
    assert len(result) == 3
    keeper = next(polygon for polygon in result if abs(polygon.area - polygon_a.area) < 1e-6 * polygon_a.area)
    loser_fragments = [polygon for polygon in result if polygon is not keeper]

    assert len(loser_fragments) == 2
    for fragment in loser_fragments:
        assert fragment.is_valid
        assert not fragment.is_empty
        assert fragment.area > BOUNDARY_TOUCH_AREA_TOLERANCE

    expected_loser_geometry = polygon_b.difference(polygon_a)
    rebuilt_loser_geometry = unary_union(loser_fragments)
    symmetric_diff_area = rebuilt_loser_geometry.symmetric_difference(expected_loser_geometry).area
    assert symmetric_diff_area <= 1e-6 * expected_loser_geometry.area


def test_many_points_more_than_four_goes_same_branch():
    polygon_a = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    polygon_b = Polygon(
        [
            (90, -10), (110, -10), (110, 10), (90, 10),
            (110, 30), (90, 30), (110, 50), (90, 50),
            (110, 70), (90, 70), (110, 90), (90, 90),
            (110, 110), (90, 110),
        ],
    )

    result, warnings = process_intersections_rebuild([polygon_a, polygon_b], 'test')

    assert warnings == []
    assert len(result) >= 1


def test_many_points_perimeter_area_filter_applied():
    thin = Polygon([(0, 0), (1000, 0), (1000, 2), (0, 2)])
    big = Polygon([(-10, -10), (999, -10), (999, 10), (-10, 10)])

    result, warnings = process_intersections_rebuild([thin, big], 'test')

    assert warnings == []
    for polygon in result:
        assert polygon.area > 0
        assert polygon.length / polygon.area <= PERIMETER_AREA_THRESHOLD


def test_many_points_branch_assigns_overlap_to_lower_damage_polygon():
    large = Polygon([(0, 0), (200, 0), (200, 200), (0, 200)])
    narrow = Polygon(
        [
            (90, -10), (110, -10), (110, 40), (90, 40),
            (110, 80), (90, 80), (110, 120), (90, 120),
            (110, 160), (90, 160), (110, 210), (90, 210),
        ],
    )

    result, warnings = process_intersections_rebuild([large, narrow], 'test')

    assert warnings == []
    assert len(result) >= 1

    max_area = max(polygon.area for polygon in result)
    assert abs(max_area - large.area) < 1e-6 * large.area


def test_handle_many_points_intersection_returns_rebuilt_and_changes_list_length():
    polygon_a = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    polygon_b = Polygon(
        [
            (20, -10), (40, -10), (40, 30), (60, 30), (60, -10), (80, -10),
            (80, 110), (60, 110), (60, 70), (40, 70), (40, 110), (20, 110),
        ],
    )
    polygons = [polygon_a, polygon_b]

    outcome = handle_many_points_intersection(
        polygons=polygons,
        first_index=0,
        second_index=1,
    )

    assert outcome.status == ManyPointsRebuildStatus.rebuilt
    assert len(polygons) >= 1

    for first_index in range(len(polygons)):
        for second_index in range(first_index + 1, len(polygons)):
            overlap_area = polygons[first_index].intersection(polygons[second_index]).area
            assert overlap_area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_many_points_branch_restart_scan_after_pair_replacement():
    polygon_a = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    polygon_b = Polygon(
        [
            (20, -10), (40, -10), (40, 30), (60, 30), (60, -10), (80, -10),
            (80, 110), (60, 110), (60, 70), (40, 70), (40, 110), (20, 110),
        ],
    )
    polygon_c = Polygon([(70, 20), (130, 20), (130, 80), (70, 80)])

    result, warnings = process_intersections_rebuild([polygon_a, polygon_b, polygon_c], 'test')

    assert warnings == []
    for first_index in range(len(result)):
        for second_index in range(first_index + 1, len(result)):
            overlap_area = result[first_index].intersection(result[second_index]).area
            assert overlap_area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_restart_scan_keeps_previously_excluded_indexes(monkeypatch):
    inner = Polygon([(-300, -300), (-280, -300), (-280, -280), (-300, -280)])
    outer = Polygon([(-320, -320), (-260, -320), (-260, -260), (-320, -260)])
    base = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    zigzag = Polygon(
        [
            (20, -10), (40, -10), (40, 30), (60, 30), (60, -10), (80, -10),
            (80, 110), (60, 110), (60, 70), (40, 70), (40, 110), (20, 110),
        ],
    )

    def fake_rebuild_outer_polygon_for_containment(outer_polygon, inner_polygon):
        return Polygon()

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments._rebuild_outer_polygon_for_containment',
        fake_rebuild_outer_polygon_for_containment,
    )

    result, warnings = process_intersections_rebuild([inner, outer, base, zigzag], 'test')

    assert len(warnings) == 1
    assert 'ошибки обработки вложенности' in warnings[0]
    # Ожидаем: inner остаётся + пара (base, zigzag) перестраивается в 3 полигона.
    assert len(result) == 4
    assert any(polygon.symmetric_difference(inner).area <= BOUNDARY_TOUCH_AREA_TOLERANCE for polygon in result)
    assert not any(polygon.symmetric_difference(outer).area <= BOUNDARY_TOUCH_AREA_TOLERANCE for polygon in result)

    for first_index in range(len(result)):
        for second_index in range(first_index + 1, len(result)):
            overlap_area = result[first_index].intersection(result[second_index]).area
            assert overlap_area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def test_process_intersections_rebuild_continues_after_first_failed_pair():
    pair_one_first = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    pair_one_second = Polygon([(5, 0), (15, 0), (15, 10), (5, 10)])
    pair_two_first = Polygon([(100, 0), (110, 0), (110, 10), (100, 10)])
    pair_two_second = Polygon([(105, 0), (115, 0), (115, 10), (105, 10)])

    result, warnings = process_intersections_rebuild(
        [pair_one_first, pair_one_second, pair_two_first, pair_two_second],
        'test',
    )

    assert result == []
    assert len(warnings) == 2
    assert all('неподдерживаемым способом' in warning for warning in warnings)


def test_extract_points_supports_point_multipoint_and_nested_geometry_collection():
    point = Point(1, 2)
    multipoint = MultiPoint([Point(3, 4), Point(5, 6)])
    nested = GeometryCollection(
        [
            LineString([(0, 0), (1, 1)]),
            GeometryCollection(
                [
                    Point(7, 8),
                    GeometryCollection([Point(9, 10)]),
                ],
            ),
        ],
    )

    point_result = extract_points(point)
    multipoint_result = extract_points(multipoint)
    nested_result = extract_points(nested)

    assert len(point_result) == 1
    assert point_result[0].equals(Point(1, 2))
    assert len(multipoint_result) == 2
    assert {item.wkt for item in multipoint_result} == {'POINT (3 4)', 'POINT (5 6)'}
    assert len(nested_result) == 2
    assert {item.wkt for item in nested_result} == {'POINT (7 8)', 'POINT (9 10)'}


def test_extract_points_returns_empty_for_linestring_intersection():
    geometry = LineString([(0, 0), (10, 0)])
    assert extract_points(geometry) == []


def test_extract_points_deduplicates_same_point_from_nested_geometries():
    geometry = GeometryCollection(
        [
            Point(3, 3),
            GeometryCollection([MultiPoint([Point(3, 3), Point(3, 3)])]),
        ],
    )

    result = extract_points(geometry)
    assert len(result) == 1
    assert result[0].equals(Point(3, 3))


def test_extract_points_deduplicates_near_equal_points_with_tolerance():
    geometry = MultiPoint([Point(5.0, 5.0), Point(5.0 + 1e-10, 5.0 - 1e-10)])
    result = extract_points(geometry)

    assert len(result) == 1
    assert result[0].equals(Point(5.0, 5.0))


def test_extract_points_does_not_deduplicate_points_outside_tolerance():
    geometry = MultiPoint([Point(5.0, 5.0), Point(5.0 + 5e-9, 5.0)])
    result = extract_points(geometry)

    assert len(result) == 2
    assert abs(result[0].x - 5.0) < 1e-12
    assert abs(result[0].y - 5.0) < 1e-12
    assert abs(result[1].x - (5.0 + 5e-9)) < 1e-12
    assert abs(result[1].y - 5.0) < 1e-12


def test_extract_points_returns_unique_points_for_real_boundary_intersection():
    geometry = GeometryCollection([Point(2, 2), MultiPoint([Point(1, 1), Point(2, 2)]), Point(3, 3)])
    result = extract_points(geometry)

    assert len(result) == 3
    assert {(point.x, point.y) for point in result} == {(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)}


def test_extract_points_from_polygon_boundary_intersection_returns_unordered_unique_points():
    polygon_1 = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    polygon_2 = Polygon([(2, -1), (6, -1), (6, 2), (2, 2)])

    boundary_intersection = polygon_1.boundary.intersection(polygon_2.boundary)
    points = extract_points(boundary_intersection)

    assert len(points) == 2
    assert {(round(point.x, 8), round(point.y, 8)) for point in points} == {(2.0, 0.0), (4.0, 2.0)}


def test_process_intersections_rebuild_exclude_outer_stops_next_pairs_for_same_outer(monkeypatch):
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner_1 = Polygon([(10, 10), (40, 10), (40, 40), (10, 40)])
    inner_2 = Polygon([(60, 60), (90, 60), (90, 90), (60, 90)])
    calls = {'count': 0}

    def fake_rebuild_outer_polygon_for_containment(outer_polygon, inner_polygon):
        calls['count'] += 1
        return Polygon()

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments._rebuild_outer_polygon_for_containment',
        fake_rebuild_outer_polygon_for_containment,
    )

    result, warnings = process_intersections_rebuild([outer, inner_1, inner_2], 'test')

    assert calls['count'] == 1
    assert len(result) == 2
    assert any(polygon.equals(inner_1) for polygon in result)
    assert any(polygon.equals(inner_2) for polygon in result)
    assert len(warnings) == 1


def test_polygon_to_polygon_line_preserves_hole():
    outer = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    hole = [(20, 20), (80, 20), (80, 80), (20, 80), (20, 20)]
    polygon = Polygon(shell=outer, holes=[hole])

    polygon_line = polygon_to_polygon_line(polygon)

    assert len(polygon_line.lines) == 2
    assert len(polygon_line.lines[0].points) == 5
    assert len(polygon_line.lines[1].points) == 5


def test_creating_segments_containment_result_saved_with_hole():
    polygon_payload = {
        'lines': [
            {
                'points': [
                    {'x': 0, 'y': 0},
                    {'x': 100, 'y': 0},
                    {'x': 100, 'y': 100},
                    {'x': 0, 'y': 100},
                    {'x': 0, 'y': 0},
                ],
            },
            {
                'points': [
                    {'x': 20, 'y': 20},
                    {'x': 80, 'y': 20},
                    {'x': 80, 'y': 80},
                    {'x': 20, 'y': 80},
                    {'x': 20, 'y': 20},
                ],
            },
        ],
    }

    with TemporaryDirectory(prefix='test_containment') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        polygon_path.write_text(json.dumps(polygon_payload), encoding='utf-8')

        storage = Storage(base_dir=base_dir)

        raw_input = {
            'parameter': {
                'name_by': 'Имени полигона',
                'segments_group': '1',
                'segments_type': '2',
                'merge_radius': 0,
                'process_intersections': 1,
            },
            'polygon': {
                'id': '12',
                'name': 'Полигон',
                'value': {'file': {'path': str(polygon_path)}},
            },
            'formation': {'name': 'пласт'},
        }

        input_data = CalculationInput.model_validate(raw_input)
        result = creating_segments(input_data, storage)

        assert result.formation is not None
        assert len(result.formation.segment) == 2

        saved_segment_paths = [segment.value.file.path for segment in result.formation.segment]
        saved_jsons = [json.loads(Path(path).read_text(encoding='utf-8')) for path in saved_segment_paths]

        reconstructed_polygons = []
        for saved_json in saved_jsons:
            shell = [(point['x'], point['y']) for point in saved_json['lines'][0]['points']]
            holes = [[(point['x'], point['y']) for point in line['points']] for line in saved_json['lines'][1:]]
            reconstructed_polygons.append(Polygon(shell=shell, holes=holes))

        outer_polygon = next(polygon for polygon in reconstructed_polygons if len(polygon.interiors) == 1)
        inner_polygon = next(polygon for polygon in reconstructed_polygons if len(polygon.interiors) == 0)

        assert len(outer_polygon.interiors) == 1
        assert abs(inner_polygon.area - 3600.0) < 1e-9
        assert abs(outer_polygon.area - (10000.0 - 3600.0)) < 1e-9


def test_process_intersections_zero_keeps_old_behavior():
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])

    result, warnings = check_intersections([outer, inner], 'test')

    assert len(result) == 0
    assert len(warnings) > 0


def test_creating_segments_process_intersections_zero_excludes_in_pipeline():
    polygon_payload = {
        'lines': [
            {
                'points': [
                    {'x': 0, 'y': 0},
                    {'x': 0, 'y': 100},
                    {'x': 100, 'y': 100},
                    {'x': 100, 'y': 0},
                    {'x': 0, 'y': 0},
                ],
            },
            {
                'points': [
                    {'x': 20, 'y': 20},
                    {'x': 20, 'y': 80},
                    {'x': 80, 'y': 80},
                    {'x': 80, 'y': 20},
                    {'x': 20, 'y': 20},
                ],
            },
        ],
    }
    with TemporaryDirectory(prefix='test_intersections_zero') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        polygon_path.write_text(json.dumps(polygon_payload), encoding='utf-8')
        storage = Storage(base_dir=base_dir)

        raw_input = {
            'parameter': {
                'name_by': 'Имени полигона',
                'segments_group': '1',
                'segments_type': '2',
                'merge_radius': 0,
                'process_intersections': 0,
            },
            'polygon': {'id': '12', 'name': 'Полигон', 'value': {'file': {'path': str(polygon_path)}}},
            'formation': {'name': 'пласт'},
        }
        input_data = CalculationInput.model_validate(raw_input)
        result = creating_segments(input_data, storage)

        assert result.formation is None
        assert result.error == [
            "Расчёт сегментов\nВсе полилинии полигона 'Полигон' исключены из-за пересечений. Расчёт не выполнен.",
        ]


def test_creating_segments_process_intersections_one_excludes_unsupported_overlap_in_pipeline():
    polygon_payload = {
        'lines': [
            {
                'points': [
                    {'x': 0, 'y': 0},
                    {'x': 0, 'y': 100},
                    {'x': 100, 'y': 100},
                    {'x': 100, 'y': 0},
                    {'x': 0, 'y': 0},
                ],
            },
            {
                'points': [
                    {'x': 50, 'y': 0},
                    {'x': 50, 'y': 100},
                    {'x': 150, 'y': 100},
                    {'x': 150, 'y': 0},
                    {'x': 50, 'y': 0},
                ],
            },
        ],
    }
    with TemporaryDirectory(prefix='test_intersections_one_overlap') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        polygon_path.write_text(json.dumps(polygon_payload), encoding='utf-8')
        storage = Storage(base_dir=base_dir)

        raw_input = {
            'parameter': {
                'name_by': 'Имени полигона',
                'segments_group': '1',
                'segments_type': '2',
                'merge_radius': 0,
                'process_intersections': 1,
            },
            'polygon': {'id': '12', 'name': 'Полигон', 'value': {'file': {'path': str(polygon_path)}}},
            'formation': {'name': 'пласт'},
        }
        input_data = CalculationInput.model_validate(raw_input)
        result = creating_segments(input_data, storage)

        assert result.formation is None
        assert result.error == [
            "Расчёт сегментов\nВсе полилинии полигона 'Полигон' исключены из-за пересечений. Расчёт не выполнен.",
        ]


def test_creating_segments_process_intersections_one_keeps_independent_polygon_with_containment():
    polygon_payload = {
        'lines': [
            {
                'points': [
                    {'x': 0, 'y': 0},
                    {'x': 0, 'y': 100},
                    {'x': 100, 'y': 100},
                    {'x': 100, 'y': 0},
                    {'x': 0, 'y': 0},
                ],
            },
            {
                'points': [
                    {'x': 20, 'y': 20},
                    {'x': 20, 'y': 80},
                    {'x': 80, 'y': 80},
                    {'x': 80, 'y': 20},
                    {'x': 20, 'y': 20},
                ],
            },
            {
                'points': [
                    {'x': 200, 'y': 200},
                    {'x': 200, 'y': 220},
                    {'x': 220, 'y': 220},
                    {'x': 220, 'y': 200},
                    {'x': 200, 'y': 200},
                ],
            },
        ],
    }
    with TemporaryDirectory(prefix='test_intersections_one_mixed') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        polygon_path.write_text(json.dumps(polygon_payload), encoding='utf-8')
        storage = Storage(base_dir=base_dir)

        raw_input = {
            'parameter': {
                'name_by': 'Имени полигона',
                'segments_group': '1',
                'segments_type': '2',
                'merge_radius': 0,
                'process_intersections': 1,
            },
            'polygon': {'id': '12', 'name': 'Полигон', 'value': {'file': {'path': str(polygon_path)}}},
            'formation': {'name': 'пласт'},
        }
        input_data = CalculationInput.model_validate(raw_input)
        result = creating_segments(input_data, storage)

        assert result.formation is not None
        assert len(result.formation.segment) == 3

        saved_segment_paths = [segment.value.file.path for segment in result.formation.segment]
        saved_jsons = [json.loads(Path(path).read_text(encoding='utf-8')) for path in saved_segment_paths]
        reconstructed_polygons = []
        for saved_json in saved_jsons:
            shell = [(point['x'], point['y']) for point in saved_json['lines'][0]['points']]
            holes = [[(point['x'], point['y']) for point in line['points']] for line in saved_json['lines'][1:]]
            reconstructed_polygons.append(Polygon(shell=shell, holes=holes))

        assert len([polygon for polygon in reconstructed_polygons if len(polygon.interiors) == 1]) == 1
        assert len([polygon for polygon in reconstructed_polygons if len(polygon.interiors) == 0]) == 2
        assert any(abs(polygon.area - 400.0) < 1e-9 for polygon in reconstructed_polygons)


def test_creating_segments_routes_by_process_intersections(monkeypatch):
    calls: list[str] = []

    def fake_check_intersections(polygons, polygon_name):
        calls.append('check')
        return polygons, []

    def fake_process_intersections_rebuild(polygons, polygon_name):
        calls.append('rebuild')
        return polygons, []

    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments.check_intersections',
        fake_check_intersections,
    )
    monkeypatch.setattr(
        'creating_segment_calculation_module.creating_segments.process_intersections_rebuild',
        fake_process_intersections_rebuild,
    )

    polygon_payload = {
        'lines': [
            {
                'points': [
                    {'x': 0, 'y': 0},
                    {'x': 0, 'y': 100},
                    {'x': 100, 'y': 100},
                    {'x': 100, 'y': 0},
                    {'x': 0, 'y': 0},
                ],
            },
        ],
    }

    with TemporaryDirectory(prefix='test_process_route') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        polygon_path.write_text(json.dumps(polygon_payload), encoding='utf-8')
        storage = Storage(base_dir=base_dir)

        raw_base = {
            'parameter': {
                'name_by': 'Имени полигона',
                'segments_group': '1',
                'segments_type': '2',
                'merge_radius': 0,
            },
            'polygon': {'id': '12', 'name': 'Полигон', 'value': {'file': {'path': str(polygon_path)}}},
            'formation': {'name': 'пласт'},
        }

        input_data_zero = CalculationInput.model_validate(
            {
                **raw_base,
                'parameter': {**raw_base['parameter'], 'process_intersections': 0},
            },
        )
        creating_segments(input_data_zero, storage)

        input_data_one = CalculationInput.model_validate(
            {
                **raw_base,
                'parameter': {**raw_base['parameter'], 'process_intersections': 1},
            },
        )
        creating_segments(input_data_one, storage)

    assert calls == ['check', 'rebuild']


def test_creating_segments_accepts_storage_with_minimal_get_temp_dir_contract():
    polygon_payload = {
        'lines': [
            {
                'points': [
                    {'x': 0, 'y': 0},
                    {'x': 0, 'y': 10},
                    {'x': 10, 'y': 10},
                    {'x': 10, 'y': 0},
                    {'x': 0, 'y': 0},
                ],
            },
        ],
    }

    class MinimalStorage:
        def __init__(self, base_dir: Path):
            self._base_dir = base_dir

        def get_temp_dir(self) -> Path:
            return self._base_dir

    with TemporaryDirectory(prefix='test_min_storage_contract') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        polygon_path.write_text(json.dumps(polygon_payload), encoding='utf-8')
        storage = MinimalStorage(base_dir)

        raw_input = {
            'parameter': {
                'name_by': 'Имени полигона',
                'segments_group': '1',
                'segments_type': '2',
                'merge_radius': 0,
                'process_intersections': 1,
            },
            'polygon': {'id': '12', 'name': 'Полигон', 'value': {'file': {'path': str(polygon_path)}}},
            'formation': {'name': 'пласт'},
        }
        input_data = CalculationInput.model_validate(raw_input)
        result = creating_segments(input_data, storage)

        assert result.formation is not None
        assert len(result.formation.segment) == 1


def test_creating_segments_saves_polygon_with_multiple_holes():
    polygon_payload = {
        'lines': [
            {
                'points': [
                    {'x': 0, 'y': 0},
                    {'x': 120, 'y': 0},
                    {'x': 120, 'y': 120},
                    {'x': 0, 'y': 120},
                    {'x': 0, 'y': 0},
                ],
            },
            {
                'points': [
                    {'x': 20, 'y': 20},
                    {'x': 40, 'y': 20},
                    {'x': 40, 'y': 40},
                    {'x': 20, 'y': 40},
                    {'x': 20, 'y': 20},
                ],
            },
            {
                'points': [
                    {'x': 70, 'y': 70},
                    {'x': 90, 'y': 70},
                    {'x': 90, 'y': 90},
                    {'x': 70, 'y': 90},
                    {'x': 70, 'y': 70},
                ],
            },
        ],
    }
    with TemporaryDirectory(prefix='test_multi_holes') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        polygon_path.write_text(json.dumps(polygon_payload), encoding='utf-8')
        storage = Storage(base_dir=base_dir)

        raw_input = {
            'parameter': {
                'name_by': 'Имени полигона',
                'segments_group': '1',
                'segments_type': '2',
                'merge_radius': 0,
                'process_intersections': 1,
            },
            'polygon': {'id': '12', 'name': 'Полигон', 'value': {'file': {'path': str(polygon_path)}}},
            'formation': {'name': 'пласт'},
        }
        input_data = CalculationInput.model_validate(raw_input)
        result = creating_segments(input_data, storage)

        assert result.formation is not None
        saved_segment_paths = [segment.value.file.path for segment in result.formation.segment]
        saved_jsons = [json.loads(Path(path).read_text(encoding='utf-8')) for path in saved_segment_paths]

        reconstructed_polygons = []
        for saved_json in saved_jsons:
            shell = [(point['x'], point['y']) for point in saved_json['lines'][0]['points']]
            holes = [[(point['x'], point['y']) for point in line['points']] for line in saved_json['lines'][1:]]
            reconstructed_polygons.append(Polygon(shell=shell, holes=holes))

        outer_polygon = next(polygon for polygon in reconstructed_polygons if len(polygon.interiors) == 2)
        assert abs(outer_polygon.area - (120 * 120 - 20 * 20 - 20 * 20)) < 1e-9


def test_two_points_branch_handles_numerically_computed_intersection_point():
    """
    Воспроизводит реальный кейс после merge_by_radius: точка пересечения
    границ вычислена численно и не лежит строго на ребре
    Проверка cut_segment в boundary не должна быть чувствительна к float-погрешности.
    """
    # Геометрия такая, какой она становится ПОСЛЕ слияния
    # (8,0) и (6,-2) с радиусом 4 в общую точку (7,-1).
    polygon_left = Polygon([(0, 0), (0, 10), (8, 10), (7, -1), (0, 0)])
    polygon_right = Polygon([(7, -1), (6, 14), (16, 14), (16, -2), (7, -1)])

    result, warnings = process_intersections_rebuild([polygon_left, polygon_right], 'test')

    # cut_segment целиком лежит на ребре (7,-1)→(6,14) правого полигона,
    # значит правый фиксируется, левый = left.difference(right).
    expected_left = polygon_left.difference(polygon_right)

    assert len(result) == 2
    assert warnings == []
    assert result[0].symmetric_difference(expected_left).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[1].symmetric_difference(polygon_right).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[0].intersection(result[1]).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
