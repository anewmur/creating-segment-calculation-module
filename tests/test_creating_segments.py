import json
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import Polygon
from shapely.ops import unary_union

from creating_segment_calculation_module.constants import BOUNDARY_TOUCH_AREA_TOLERANCE
from creating_segment_calculation_module.constants import PERIMETER_AREA_THRESHOLD
from creating_segment_calculation_module.creating_segments import check_intersections
from creating_segment_calculation_module.creating_segments import creating_segments
from creating_segment_calculation_module.polygon_serialization import polygon_to_polygon_line
from creating_segment_calculation_module.creating_segments import process_intersections_rebuild
from creating_segment_calculation_module.models.creating_segments import CalculationInput

from tests.utils import Storage


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def _polygon_payload(lines: list[list[tuple[float, float]]]) -> dict:
    payload_lines = []
    for coords in lines:
        points = []
        for coord_x, coord_y in coords:
            points.append({'x': coord_x, 'y': coord_y})
        payload_lines.append({'points': points})
    return {'lines': payload_lines}


def _calculation_input(
    polygon_path: Path,
    process_intersections: int = 1,
    merge_radius: float = 0,
) -> CalculationInput:
    raw_input = {
        'parameter': {
            'name_by': 'Имени полигона',
            'segments_group': '1',
            'segments_type': '2',
            'merge_radius': merge_radius,
            'process_intersections': process_intersections,
        },
        'polygon': {
            'id': '12',
            'name': 'Полигон',
            'value': {'file': {'path': str(polygon_path)}},
        },
        'formation': {'name': 'пласт'},
    }
    return CalculationInput.model_validate(raw_input)


def _read_saved_jsons(result) -> list[dict]:
    saved_jsons = []
    for segment in result.formation.segment:
        path = Path(segment.value.file.path)
        saved_jsons.append(json.loads(path.read_text(encoding='utf-8')))
    return saved_jsons


def _reconstruct_polygon(saved_json: dict) -> Polygon:
    shell = [(point['x'], point['y']) for point in saved_json['lines'][0]['points']]
    holes = []
    for line in saved_json['lines'][1:]:
        holes.append([(point['x'], point['y']) for point in line['points']])
    return Polygon(shell=shell, holes=holes)


def _assert_no_area_overlaps(polygons: list[Polygon]) -> None:
    for first_index in range(len(polygons)):
        for second_index in range(first_index + 1, len(polygons)):
            overlap_area = polygons[first_index].intersection(polygons[second_index]).area
            assert overlap_area <= BOUNDARY_TOUCH_AREA_TOLERANCE


def _assert_union_area_preserved(
    source_polygons: list[Polygon],
    result_polygons: list[Polygon],
) -> None:
    source_area = unary_union(source_polygons).area
    result_area = sum(polygon.area for polygon in result_polygons)
    assert abs(result_area - source_area) <= 1e-6 * source_area


def test_parameter_defaults_and_explicit_values():
    default_input = {
        'parameter': {
            'name_by': 'Имени полигона',
            'segments_group': '1',
            'segments_type': '2',
        },
        'polygon': {
            'id': '1',
            'name': 'test',
            'value': {'file': {'path': '/tmp/test'}},
        },
        'formation': {'name': 'пласт'},
    }
    explicit_input = {
        'parameter': {
            'name_by': 'Имени полигона',
            'segments_group': '1',
            'segments_type': '2',
            'merge_radius': 7,
            'process_intersections': 0,
        },
        'polygon': {
            'id': '1',
            'name': 'test',
            'value': {'file': {'path': '/tmp/test'}},
        },
        'formation': {'name': 'пласт'},
    }

    default_data = CalculationInput.model_validate(default_input)
    explicit_data = CalculationInput.model_validate(explicit_input)

    assert default_data.parameter.merge_radius == 20
    assert default_data.parameter.process_intersections == 1
    assert explicit_data.parameter.merge_radius == 7
    assert explicit_data.parameter.process_intersections == 0


def test_check_intersections_excludes_real_overlap_but_keeps_tiny_numerical_overlap():
    overlapping_first = Polygon([(0, 0), (0, 500), (500, 500), (500, 0), (0, 0)])
    overlapping_second = Polygon([(250, 0), (250, 500), (750, 500), (750, 0), (250, 0)])
    almost_touching_first = Polygon([(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)])
    almost_touching_second = Polygon(
        [(9.9999995, 0), (9.9999995, 10), (20, 10), (20, 0), (9.9999995, 0)],
    )

    excluded_polygons, warnings = check_intersections(
        [overlapping_first, overlapping_second],
        'Полигон',
    )

    kept_polygons, tiny_warnings = check_intersections(
        [almost_touching_first, almost_touching_second],
        'Полигон',
    )

    assert excluded_polygons == []
    assert len(warnings) == 1
    assert len(kept_polygons) == 2
    assert tiny_warnings == []


def test_creating_segments_clips_by_model_border_and_saves_only_inside_part():
    with TemporaryDirectory(prefix='test_creating_segment') as base_dir_str:
        base_dir = Path(base_dir_str)
        border_path = base_dir / 'border.json'
        polygon_path = base_dir / 'polygon.json'
        border_payload = _polygon_payload([
            [(0, 0), (0, 1000), (1000, 1000), (1000, 0), (0, 0)],
        ])
        polygon_payload = _polygon_payload([
            [(0, 0), (0, 500), (500, 500), (500, 0), (0, 0)],
            [(-10, -20), (-10, -500), (-400, -500), (-500, -50), (-10, -20)],
        ])
        _write_json(border_path, border_payload)
        _write_json(polygon_path, polygon_payload)

        raw_input = _calculation_input(polygon_path).model_dump()
        raw_input['formation_model'] = {
            'border_model': {'file': {'path': str(border_path)}},
        }
        input_data = CalculationInput.model_validate(raw_input)

        result = creating_segments(input_data, Storage(base_dir=base_dir))
        saved_json = _read_saved_jsons(result)[0]

    assert result.messages.error == []
    assert len(result.messages.warning) == 1
    assert result.messages.info == ['Расчёт сегментов\nУспешно создано сегментов: 1']
    assert saved_json == _polygon_payload([
        [(0.0, 0.0), (0.0, 500.0), (500.0, 500.0), (500.0, 0.0), (0.0, 0.0)],
    ])
def test_creating_segments_removes_duplicate_closed_lines_by_edges():
    duplicate_payload = _polygon_payload([
        [(0, 0), (0, 100), (100, 100), (100, 0), (0, 0)],
        [(100, 100), (100, 0), (0, 0), (0, 100), (100, 100)],
        [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)],
    ])

    with TemporaryDirectory(prefix='test_duplicate_lines') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        _write_json(polygon_path, duplicate_payload)

        result = creating_segments(
            _calculation_input(polygon_path),
            Storage(base_dir=base_dir),
        )
        saved_json = _read_saved_jsons(result)[0]

    assert result.messages.error == []
    assert len(result.formation.segment) == 1
    assert saved_json == _polygon_payload([
        [(0, 0), (0, 100), (100, 100), (100, 0), (0, 0)],
    ])
    assert any(
        'повтор' in warning.lower() or 'дубли' in warning.lower()
        for warning in result.messages.warning
    )


def test_creating_segments_saves_each_result_polygon_as_separate_segment():
    polygon_payload = _polygon_payload([
        [(0, 0), (0, 100), (100, 100), (100, 0), (0, 0)],
        [(200, 0), (200, 100), (300, 100), (300, 0), (200, 0)],
    ])

    with TemporaryDirectory(prefix='test_separate_segments') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        _write_json(polygon_path, polygon_payload)

        result = creating_segments(
            _calculation_input(polygon_path),
            Storage(base_dir=base_dir),
        )

        assert result.messages.error == []
        assert len(result.formation.segment) == 2
        assert result.formation.segment[0].name == 'Полигон'
        assert result.formation.segment[1].name == 'Полигон (1)'
        assert result.messages.info == ['Расчёт сегментов\nУспешно создано сегментов: 2']
        assert Path(result.formation.segment[0].value.file.path).exists()
        assert Path(result.formation.segment[1].value.file.path).exists()
        assert result.formation.segment[0].value.file.path != result.formation.segment[1].value.file.path

def test_process_intersections_rebuild_containment_keeps_inner_and_makes_hole():
    outer = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    inner = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])

    result, warnings = process_intersections_rebuild([outer, inner], 'test')

    rebuilt_outer = next(polygon for polygon in result if len(polygon.interiors) == 1)
    preserved_inner = next(polygon for polygon in result if len(polygon.interiors) == 0)

    assert warnings == []
    assert len(result) == 2
    assert abs(rebuilt_outer.area - (outer.area - inner.area)) < 1e-9
    assert abs(preserved_inner.area - inner.area) < 1e-9
    _assert_no_area_overlaps(result)


def test_creating_segments_names_segments_by_well_name():
    polygon_payload = _polygon_payload([
        [(0, 0), (0, 100), (100, 100), (100, 0), (0, 0)],
        [(200, 0), (200, 100), (300, 100), (300, 0), (200, 0)],
    ])

    with TemporaryDirectory(prefix='test_segments_by_well_name') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        _write_json(polygon_path, polygon_payload)

        raw_input = _calculation_input(polygon_path).model_dump()
        raw_input['parameter']['name_by'] = 'Имени ствола'
        raw_input['well'] = [
            {
                'name': 'Скв1',
                'target': {
                    'point': [
                        {'x': 50, 'y': 50},
                    ],
                },
            },
        ]

        result = creating_segments(
            CalculationInput.model_validate(raw_input),
            Storage(base_dir=base_dir),
        )

    assert result.messages.error == []
    assert len(result.formation.segment) == 2
    assert result.formation.segment[0].name == 'Скв1'
    assert result.formation.segment[1].name == 'Сегмент'

def test_two_points_rebuild_splits_overlap_without_losing_union_area():
    square_left = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    square_right = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])

    result, warnings = process_intersections_rebuild([square_left, square_right], 'test')

    assert warnings == []
    assert len(result) == 2
    assert result[0].boundary.intersection(result[1].boundary).length > 0
    _assert_no_area_overlaps(result)
    _assert_union_area_preserved([square_left, square_right], result)


def test_two_points_rebuild_keeps_fixed_boundary_polygon_and_rebuilds_other():
    polygon_left = Polygon([(0, 0), (0, 10), (8, 10), (8, 0), (0, 0)])
    polygon_right = Polygon([(6, -2), (6, 14), (16, 14), (16, -2), (6, -2)])
    expected_left = polygon_left.difference(polygon_right)

    result, warnings = process_intersections_rebuild([polygon_left, polygon_right], 'test')

    assert warnings == []
    assert len(result) == 2
    assert result[0].symmetric_difference(expected_left).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[1].symmetric_difference(polygon_right).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    _assert_no_area_overlaps(result)


def test_two_points_rebuild_tolerates_numerically_computed_intersection_point():
    polygon_left = Polygon([(0, 0), (0, 10), (8, 10), (7, -1), (0, 0)])
    polygon_right = Polygon([(7, -1), (6, 14), (16, 14), (16, -2), (7, -1)])
    expected_left = polygon_left.difference(polygon_right)

    result, warnings = process_intersections_rebuild([polygon_left, polygon_right], 'test')

    assert warnings == []
    assert len(result) == 2
    assert result[0].symmetric_difference(expected_left).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[1].symmetric_difference(polygon_right).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    _assert_no_area_overlaps(result)


def test_process_intersections_rebuild_clears_chain_of_two_point_overlaps():
    polygon_center = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    polygon_right = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])
    polygon_left = Polygon([(-5, 5), (5, 5), (5, 15), (-5, 15)])

    result, warnings = process_intersections_rebuild(
        [polygon_center, polygon_right, polygon_left],
        'test',
    )

    assert warnings == []
    assert len(result) == 3
    _assert_no_area_overlaps(result)


def test_many_points_rebuild_handles_geometry_collection_intersection():
    polygon_left = Polygon([(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)])
    polygon_right = Polygon(
        [(10, 0), (30, 0), (30, 25), (0, 25), (0, 20), (10, 20), (10, 0)],
    )
    raw_intersection = polygon_left.intersection(polygon_right)

    result, warnings = process_intersections_rebuild([polygon_left, polygon_right], 'test')

    assert raw_intersection.geom_type == 'GeometryCollection'
    assert warnings == []
    assert len(result) == 2
    _assert_no_area_overlaps(result)
    _assert_union_area_preserved([polygon_left, polygon_right], result)


def test_many_points_rebuild_filters_bad_thin_fragments():
    base = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    thin_comb = Polygon(
        [
            (20, -10), (21, -10), (21, 30), (40, 30), (40, -10), (41, -10),
            (41, 110), (40, 110), (40, 70), (21, 70), (21, 110), (20, 110),
        ],
    )

    result, warnings = process_intersections_rebuild([base, thin_comb], 'test')

    assert warnings == []
    assert len(result) == 1
    assert result[0].symmetric_difference(base).area <= BOUNDARY_TOUCH_AREA_TOLERANCE
    assert result[0].length / result[0].area <= PERIMETER_AREA_THRESHOLD


def test_many_points_rebuild_keeps_valid_fragments_for_vertical_strip_case():
    square = Polygon([(0, 0), (0, 100), (100, 100), (100, 0)])
    vertical_strip = Polygon([(35, -40), (35, 140), (65, 140), (65, -40)])

    result, warnings = process_intersections_rebuild([square, vertical_strip], 'test')

    keeper = next(
        polygon
        for polygon in result
        if abs(polygon.area - square.area) <= 1e-6 * square.area
    )
    loser_fragments = [polygon for polygon in result if polygon is not keeper]
    expected_loser_geometry = vertical_strip.difference(square)
    rebuilt_loser_geometry = unary_union(loser_fragments)

    assert warnings == []
    assert len(result) == 3
    assert len(loser_fragments) == 2
    assert (
        rebuilt_loser_geometry.symmetric_difference(expected_loser_geometry).area
        <= 1e-6 * expected_loser_geometry.area
    )
    _assert_no_area_overlaps(result)


def test_many_points_rebuild_restarts_scan_after_pair_replacement():
    polygon_left = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    polygon_middle = Polygon(
        [
            (20, -10), (40, -10), (40, 30), (60, 30), (60, -10), (80, -10),
            (80, 110), (60, 110), (60, 70), (40, 70), (40, 110), (20, 110),
        ],
    )
    polygon_right = Polygon([(70, 20), (130, 20), (130, 80), (70, 80)])

    result, warnings = process_intersections_rebuild(
        [polygon_left, polygon_middle, polygon_right],
        'test',
    )

    assert warnings == []
    _assert_no_area_overlaps(result)


def test_process_intersections_zero_excludes_overlap_in_pipeline():
    polygon_payload = _polygon_payload([
        [(0, 0), (0, 100), (100, 100), (100, 0), (0, 0)],
        [(20, 20), (20, 80), (80, 80), (80, 20), (20, 20)],
    ])

    with TemporaryDirectory(prefix='test_intersections_zero') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        _write_json(polygon_path, polygon_payload)

        result = creating_segments(
            _calculation_input(polygon_path, process_intersections=0),
            Storage(base_dir=base_dir),
        )

    assert result.formation is None
    assert result.messages.error == [
        "Расчёт сегментов\nВсе полилинии полигона 'Полигон' исключены из-за пересечений. Расчёт не выполнен.",
    ]


def test_process_intersections_one_rebuilds_overlap_in_pipeline():
    polygon_payload = _polygon_payload([
        [(0, 0), (0, 100), (100, 100), (100, 0), (0, 0)],
        [(50, 0), (50, 100), (150, 100), (150, 0), (50, 0)],
    ])

    with TemporaryDirectory(prefix='test_intersections_one_overlap') as base_dir_str:
        base_dir = Path(base_dir_str)
        polygon_path = base_dir / 'polygon.json'
        _write_json(polygon_path, polygon_payload)

        result = creating_segments(
            _calculation_input(polygon_path, process_intersections=1),
            Storage(base_dir=base_dir),
        )
        polygons = [
            _reconstruct_polygon(saved_json)
            for saved_json in _read_saved_jsons(result)
        ]

    assert result.messages.error == []
    assert len(polygons) == 2
    _assert_no_area_overlaps(polygons)
    _assert_no_area_overlaps(polygons)


def test_polygon_to_polygon_line_preserves_hole():
    outer = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    hole = [(20, 20), (80, 20), (80, 80), (20, 80), (20, 20)]
    polygon = Polygon(shell=outer, holes=[hole])

    polygon_line = polygon_to_polygon_line(polygon)

    assert len(polygon_line.lines) == 2
    assert len(polygon_line.lines[0].points) == 5
    assert len(polygon_line.lines[1].points) == 5
