from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..models.enumirations import ManyPointsRebuildStatus


class ManyPointsOverlapHandler:
    """Обрабатывает сложные пересечения пары полигонов."""

    def __init__(
        self,
        boundary_touch_area_tolerance: float,
        perimeter_area_threshold: float,
    ) -> None:
        self._boundary_touch_area_tolerance = boundary_touch_area_tolerance
        self._perimeter_area_threshold = perimeter_area_threshold

    def _collect_polygon_components(self, geometry: BaseGeometry) -> list[Polygon]:
        polygons: list[Polygon] = []

        if geometry.is_empty:
            return polygons

        if geometry.geom_type == 'Polygon':
            if geometry.is_valid and geometry.area > self._boundary_touch_area_tolerance:
                polygons.append(geometry)
            return polygons

        if geometry.geom_type == 'MultiPolygon':
            for polygon in geometry.geoms:
                if polygon.is_valid and polygon.area > self._boundary_touch_area_tolerance:
                    polygons.append(polygon)
            return polygons

        if geometry.geom_type == 'GeometryCollection':
            for polygon in geometry.geoms:
                polygons.extend(self._collect_polygon_components(polygon))
            return polygons

        return polygons

    def _passes_perimeter_area_filter(self, polygon: Polygon) -> bool:
        if not polygon.is_valid:
            return False
        if polygon.is_empty:
            return False
        if polygon.area <= self._boundary_touch_area_tolerance:
            return False
        return polygon.length / polygon.area <= self._perimeter_area_threshold

    def _replace_pair_with_polygons(
        self,
        polygons: list[Polygon],
        first_index: int,
        second_index: int,
        replacement_polygons: list[Polygon],
    ) -> None:
        larger_index = max(first_index, second_index)
        smaller_index = min(first_index, second_index)
        del polygons[larger_index]
        del polygons[smaller_index]
        polygons[smaller_index:smaller_index] = replacement_polygons

    def _get_valid_intersection_geometry(
        self,
        poly_i: Polygon,
        poly_j: Polygon,
    ) -> BaseGeometry | None:
        if poly_i.area <= 0 or poly_j.area <= 0:
            return None

        intersection_geom = poly_i.intersection(poly_j)
        if intersection_geom.is_empty:
            return None
        if not intersection_geom.is_valid:
            return None

        if intersection_geom.geom_type == 'GeometryCollection':
            polygonal_parts = self._collect_polygon_components(intersection_geom)
            if not polygonal_parts:
                return None
            intersection_geom = unary_union(polygonal_parts)

        if intersection_geom.geom_type not in {'Polygon', 'MultiPolygon'}:
            return None
        if intersection_geom.area <= self._boundary_touch_area_tolerance:
            return None

        return intersection_geom

    def _select_keeper_and_loser_indexes(
        self,
        poly_i: Polygon,
        poly_j: Polygon,
        intersection_geom: BaseGeometry,
        first_index: int,
        second_index: int,
    ) -> tuple[int, int]:
        ratio_i = intersection_geom.area / poly_i.area
        ratio_j = intersection_geom.area / poly_j.area

        if ratio_i <= ratio_j:
            return first_index, second_index
        return second_index, first_index

    def _build_pre_filter_polygons(
        self,
        polygons: list[Polygon],
        keeper_index: int,
        loser_index: int,
        intersection_geom: BaseGeometry,
    ) -> list[Polygon] | None:
        keeper_polygon = polygons[keeper_index]
        loser_polygon = polygons[loser_index]
        loser_rebuilt_geom = loser_polygon.difference(intersection_geom)
        loser_parts = self._collect_polygon_components(loser_rebuilt_geom)

        pre_filter_polygons = [keeper_polygon, *loser_parts]

        for polygon in pre_filter_polygons:
            if polygon.is_empty:
                return None
            if not polygon.is_valid:
                return None
            if polygon.area <= self._boundary_touch_area_tolerance:
                return None

        return pre_filter_polygons

    def _polygons_have_no_significant_overlap(self, polygons: list[Polygon]) -> bool:
        for first_part_index in range(len(polygons)):
            for second_part_index in range(first_part_index + 1, len(polygons)):
                overlap_area = polygons[first_part_index].intersection(polygons[second_part_index]).area
                if overlap_area > self._boundary_touch_area_tolerance:
                    return False
        return True

    def _areas_match_original_union(
        self,
        poly_i: Polygon,
        poly_j: Polygon,
        rebuilt_polygons: list[Polygon],
    ) -> bool:
        original_union_area = poly_i.union(poly_j).area
        if original_union_area <= 0:
            return False

        rebuilt_area = sum(polygon.area for polygon in rebuilt_polygons)
        return abs(rebuilt_area - original_union_area) <= 1e-6 * original_union_area

    def _filter_replacement_polygons(self, polygons: list[Polygon]) -> list[Polygon]:
        replacement_polygons: list[Polygon] = []
        for polygon in polygons:
            if self._passes_perimeter_area_filter(polygon):
                replacement_polygons.append(polygon)
        return replacement_polygons

    def handle(
        self,
        polygons: list[Polygon],
        first_index: int,
        second_index: int,
    ) -> ManyPointsRebuildStatus:
        """Перестраивает пару в ветке сложного (многоточечного) пересечения."""
        poly_i = polygons[first_index]
        poly_j = polygons[second_index]

        intersection_geom = self._get_valid_intersection_geometry(poly_i, poly_j)
        if intersection_geom is None:
            return ManyPointsRebuildStatus.rebuild_failed

        keeper_index, loser_index = self._select_keeper_and_loser_indexes(
            poly_i,
            poly_j,
            intersection_geom,
            first_index,
            second_index,
        )

        pre_filter_polygons = self._build_pre_filter_polygons(
            polygons,
            keeper_index,
            loser_index,
            intersection_geom,
        )
        if pre_filter_polygons is None:
            return ManyPointsRebuildStatus.rebuild_failed

        if not self._polygons_have_no_significant_overlap(pre_filter_polygons):
            return ManyPointsRebuildStatus.rebuild_failed

        if not self._areas_match_original_union(poly_i, poly_j, pre_filter_polygons):
            return ManyPointsRebuildStatus.rebuild_failed

        replacement_polygons = self._filter_replacement_polygons(pre_filter_polygons)
        self._replace_pair_with_polygons(
            polygons=polygons,
            first_index=first_index,
            second_index=second_index,
            replacement_polygons=replacement_polygons,
        )
        return ManyPointsRebuildStatus.rebuilt
