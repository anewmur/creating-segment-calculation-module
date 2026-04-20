from collections.abc import Callable

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from ..models.enumirations import ContainmentHandlingResult, ContainmentHandlingStatus


class ContainmentHandler:
    """Обрабатывает вложенность полигонов."""

    def __init__(self, rebuild_outer_polygon: Callable[[Polygon, Polygon], BaseGeometry]) -> None:
        self._rebuild_outer_polygon = rebuild_outer_polygon

    def handle(
        self,
        polygons: list[Polygon],
        first_index: int,
        second_index: int,
    ) -> ContainmentHandlingResult:
        """Перестраивает пару как вложенность или возвращает not_containment."""
        first_polygon = polygons[first_index]
        second_polygon = polygons[second_index]

        if first_polygon.contains(second_polygon):
            outer_index = first_index
            inner_index = second_index
        elif second_polygon.contains(first_polygon):
            outer_index = second_index
            inner_index = first_index
        else:
            return ContainmentHandlingResult(status=ContainmentHandlingStatus.not_containment)

        outer_polygon = polygons[outer_index]
        inner_polygon = polygons[inner_index]
        rebuilt_outer = self._rebuild_outer_polygon(outer_polygon, inner_polygon)

        if (
            rebuilt_outer.is_empty
            or rebuilt_outer.geom_type != 'Polygon'
            or not rebuilt_outer.is_valid
            or len(rebuilt_outer.interiors) < 1
        ):
            return ContainmentHandlingResult(
                status=ContainmentHandlingStatus.exclude_outer,
                outer_index=outer_index,
            )

        polygons[outer_index] = rebuilt_outer
        return ContainmentHandlingResult(
            status=ContainmentHandlingStatus.rebuilt,
            outer_index=outer_index,
        )
