from shapely.errors import GEOSException
from shapely.geometry import LineString
from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import split
from shapely.ops import unary_union

class TwoPointsOverlapHandler:
    """Обрабатывает пересечение пары в сценарии двух граничных точек."""

    def __init__(
        self,
        point_dedup_tolerance: float,
        shared_edge_tolerance: float,
        boundary_touch_area_tolerance: float,
    ) -> None:
        self._point_dedup_tolerance = point_dedup_tolerance
        self._shared_edge_tolerance = shared_edge_tolerance
        self._boundary_touch_area_tolerance = boundary_touch_area_tolerance

    def _as_rebuilt_polygon_or_none(self, geometry: BaseGeometry) -> Polygon | None:
        if geometry.is_empty or not geometry.is_valid:
            return None
        if geometry.geom_type != 'Polygon':
            return None
        return geometry

    def _is_polygonal_geometry(self, geometry: BaseGeometry) -> bool:
        return geometry.geom_type in {'Polygon', 'MultiPolygon'} and geometry.is_valid and not geometry.is_empty

    def _collect_split_halves(self, overlap: BaseGeometry, cut_segment: LineString) -> list[Polygon]:
        try:
            split_result = split(overlap, cut_segment)
        except (GEOSException, TypeError, ValueError):
            return []

        halves: list[Polygon] = []
        for geometry in split_result.geoms:
            if geometry.geom_type != 'Polygon':
                continue
            if not geometry.is_valid:
                continue
            if geometry.area <= self._boundary_touch_area_tolerance:
                continue
            halves.append(geometry)

        return halves

    def _assign_half_to_polygon(self, half: Polygon, only_i: BaseGeometry, only_j: BaseGeometry) -> int | None:
        shared_len_with_i = half.boundary.intersection(only_i.boundary).length
        shared_len_with_j = half.boundary.intersection(only_j.boundary).length

        if shared_len_with_i > shared_len_with_j + self._shared_edge_tolerance:
            return 0
        if shared_len_with_j > shared_len_with_i + self._shared_edge_tolerance:
            return 1

        return None

    def _build_cut_segment(self, first_point: Point, second_point: Point) -> LineString:
        return LineString([(first_point.x, first_point.y), (second_point.x, second_point.y)])

    def _segment_matches_polygon_boundary(self, polygon: Polygon, cut_segment: LineString) -> bool:
        return polygon.boundary.buffer(self._point_dedup_tolerance).covers(cut_segment)

    def _validate_two_point_rebuild_inputs(
        self,
        poly_i: Polygon,
        poly_j: Polygon,
    ) -> tuple[BaseGeometry, BaseGeometry, BaseGeometry] | None:
        only_i = poly_i.difference(poly_j)
        only_j = poly_j.difference(poly_i)
        overlap = poly_i.intersection(poly_j)

        if not self._is_polygonal_geometry(only_i):
            return None
        if not self._is_polygonal_geometry(only_j):
            return None
        if not self._is_polygonal_geometry(overlap):
            return None

        return only_i, only_j, overlap

    def _rebuild_polygons_from_overlap(
        self,
        only_i: BaseGeometry,
        only_j: BaseGeometry,
        overlap: BaseGeometry,
        cut_segment: LineString,
    ) -> tuple[Polygon, Polygon] | None:
        halves = self._collect_split_halves(overlap, cut_segment)
        if len(halves) != 2:
            return None

        half_for_i: Polygon | None = None
        half_for_j: Polygon | None = None
        for half in halves:
            assignment = self._assign_half_to_polygon(half, only_i, only_j)
            if assignment is None:
                return None
            if assignment == 0:
                if half_for_i is not None:
                    return None
                half_for_i = half
                continue
            if half_for_j is not None:
                return None
            half_for_j = half

        if half_for_i is None or half_for_j is None:
            return None

        new_poly_i = self._as_rebuilt_polygon_or_none(unary_union([only_i, half_for_i]))
        new_poly_j = self._as_rebuilt_polygon_or_none(unary_union([only_j, half_for_j]))
        if new_poly_i is None or new_poly_j is None:
            return None

        return new_poly_i, new_poly_j

    def _rebuild_other_by_fixed_boundary_polygon(
        self,
        polygons: list[Polygon],
        fixed_index: int,
        other_index: int,
    ) -> bool:
        fixed_polygon = polygons[fixed_index]
        other_polygon = polygons[other_index]

        new_other_geom = other_polygon.difference(fixed_polygon)
        new_other = self._as_rebuilt_polygon_or_none(new_other_geom)
        if new_other is None:
            return False

        if fixed_polygon.intersection(new_other).area > self._boundary_touch_area_tolerance:
            return False

        union_area = fixed_polygon.union(other_polygon).area
        if union_area <= 0:
            return False

        rebuilt_area = fixed_polygon.area + new_other.area
        if abs(rebuilt_area - union_area) > 1e-6 * union_area:
            return False

        polygons[fixed_index] = fixed_polygon
        polygons[other_index] = new_other
        return True

    def _validate_rebuilt_pair(
        self,
        poly_i: Polygon,
        poly_j: Polygon,
        new_poly_i: Polygon,
        new_poly_j: Polygon,
    ) -> bool:
        if not new_poly_i.is_valid or not new_poly_j.is_valid:
            return False
        if new_poly_i.intersection(new_poly_j).area > self._boundary_touch_area_tolerance:
            return False

        union_area = poly_i.union(poly_j).area
        if union_area <= 0:
            return False

        rebuilt_area = new_poly_i.area + new_poly_j.area
        if abs(rebuilt_area - union_area) > 1e-6 * union_area:
            return False

        shared_boundary_length = new_poly_i.boundary.intersection(new_poly_j.boundary).length
        return shared_boundary_length > self._point_dedup_tolerance

    def handle(
        self,
        polygons: list[Polygon],
        first_index: int,
        second_index: int,
        first_intersection_point: Point,
        second_intersection_point: Point,
    ) -> bool:
        """Перестраивает пару в сценарии двух точек пересечения границ."""
        cut_segment = self._build_cut_segment(first_intersection_point, second_intersection_point)

        poly_i = polygons[first_index]
        poly_j = polygons[second_index]
        cut_on_first = self._segment_matches_polygon_boundary(poly_i, cut_segment)
        cut_on_second = self._segment_matches_polygon_boundary(poly_j, cut_segment)

        if cut_on_first and not cut_on_second:
            return self._rebuild_other_by_fixed_boundary_polygon(
                polygons=polygons,
                fixed_index=first_index,
                other_index=second_index,
            )

        if cut_on_second and not cut_on_first:
            return self._rebuild_other_by_fixed_boundary_polygon(
                polygons=polygons,
                fixed_index=second_index,
                other_index=first_index,
            )

        if cut_on_first and cut_on_second:
            return False

        prepared_geometries = self._validate_two_point_rebuild_inputs(poly_i, poly_j)
        if prepared_geometries is None:
            return False

        only_i, only_j, overlap = prepared_geometries
        rebuilt_pair = self._rebuild_polygons_from_overlap(only_i, only_j, overlap, cut_segment)
        if rebuilt_pair is None:
            return False

        new_poly_i, new_poly_j = rebuilt_pair
        if not self._validate_rebuilt_pair(poly_i, poly_j, new_poly_i, new_poly_j):
            return False

        polygons[first_index] = new_poly_i
        polygons[second_index] = new_poly_j
        return True
