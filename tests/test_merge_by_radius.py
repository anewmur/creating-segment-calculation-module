import math

from shapely.geometry import Polygon

from creating_segment_calculation_module.creating_segments import merge_by_radius


def test_merge_by_radius_simple_merge_two_vertices():
    polygon_1 = Polygon([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)])
    polygon_2 = Polygon([(5, 0), (20, 0), (20, -10), (5, 0)])

    result_polygons, warnings, infos = merge_by_radius([polygon_1, polygon_2], 1.5, 'Полигон')

    assert len(result_polygons) == 2
    assert warnings == []
    assert infos == []

    coords_1 = list(result_polygons[0].exterior.coords)
    coords_2 = list(result_polygons[1].exterior.coords)

    has_merged_point_in_first = any(
        math.isclose(coord_x, 4.5, abs_tol=1e-9) and math.isclose(coord_y, 0.0, abs_tol=1e-9)
        for coord_x, coord_y in coords_1
    )
    has_merged_point_in_second = any(
        math.isclose(coord_x, 4.5, abs_tol=1e-9) and math.isclose(coord_y, 0.0, abs_tol=1e-9)
        for coord_x, coord_y in coords_2
    )

    assert has_merged_point_in_first
    assert has_merged_point_in_second


def test_merge_by_radius_skips_when_same_neighbor_has_two_vertices_in_radius():
    polygon_1 = Polygon([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)])
    polygon_2 = Polygon([(5, 0), (5, 1), (20, 1), (20, 0), (5, 0)])

    result_polygons, warnings, infos = merge_by_radius([polygon_1, polygon_2], 1.5, 'Полигон')

    assert len(result_polygons) == 2
    assert warnings == []
    assert infos == [
        'Расчёт сегментов\n'
        'Для некоторых полилиний полигона Полигон в радиус склейки входит более 1 точки одной полилинии. '
        'Склейка не будет выполнена.',
    ]

    coords_1 = list(result_polygons[0].exterior.coords)
    coords_2 = list(result_polygons[1].exterior.coords)

    assert infos == [
        'Расчёт сегментов\n'
        'Для некоторых полилиний полигона Полигон в радиус склейки входит более 1 точки одной полилинии. '
        'Склейка не будет выполнена.',
    ]
    assert warnings == []
    assert len(result_polygons) == 2


def test_merge_by_radius_keeps_polygon_closed():
    polygon_1 = Polygon([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)])
    polygon_2 = Polygon([(1, 0), (20, 0), (20, -10), (1, 0)])

    result_polygons, warnings, infos = merge_by_radius([polygon_1, polygon_2], 1.5, 'Полигон')

    assert warnings == []
    assert infos == []

    for polygon in result_polygons:
        coords = list(polygon.exterior.coords)
        assert coords[0] == coords[-1]


def test_merge_by_radius_excludes_polygon_after_self_intersection():
    # p1 — вогнутый полигон с впадиной (6,5)-(8,8).
    # При сдвиге (10,10) -> (10,12) ребро пересечёт само себя.
    polygon_1 = Polygon([(0, 0), (10, 0), (10, 10), (6, 5), (8, 8), (0, 10), (0, 0)])
    # p2 — треугольник с вершиной (10,14), которая попадает в радиус 5 только от (10,10).
    polygon_2 = Polygon([(10, 14), (20, 14), (20, 20), (10, 14)])

    result_polygons, warnings, infos = merge_by_radius(polygons= [polygon_1, polygon_2], merge_radius=5.0, polygon_name='Полигон')

    assert len(result_polygons) == 1
    assert infos == []
    assert warnings == [
        'Расчёт сегментов\n'
        'Полилиния полигона Полигон исключена из расчёта из-за самопересечения после склейки.',
    ]