import matplotlib
matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
from shapely.geometry import GeometryCollection
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.geometry import MultiPoint
from shapely.geometry import MultiPolygon
from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry


def _draw_geometry_on_axes(
    axes,
    geometry: BaseGeometry,
    label: str,
) -> None:
    if geometry.is_empty:
        return

    if isinstance(geometry, Point):
        axes.plot(geometry.x, geometry.y, marker="o", linestyle="None", label=label)
        return

    if isinstance(geometry, MultiPoint):
        first_item = True
        for point_geometry in geometry.geoms:
            point_label = label if first_item else None
            axes.plot(
                point_geometry.x,
                point_geometry.y,
                marker="o",
                linestyle="None",
                label=point_label,
            )
            first_item = False
        return

    if isinstance(geometry, LineString):
        coordinate_sequence = list(geometry.coords)
        x_values = [coordinate[0] for coordinate in coordinate_sequence]
        y_values = [coordinate[1] for coordinate in coordinate_sequence]
        axes.plot(x_values, y_values, marker="o", label=label)
        return

    if isinstance(geometry, MultiLineString):
        first_item = True
        for line_geometry in geometry.geoms:
            coordinate_sequence = list(line_geometry.coords)
            x_values = [coordinate[0] for coordinate in coordinate_sequence]
            y_values = [coordinate[1] for coordinate in coordinate_sequence]
            line_label = label if first_item else None
            axes.plot(x_values, y_values, marker="o", label=line_label)
            first_item = False
        return

    if isinstance(geometry, Polygon):
        exterior_coordinates = list(geometry.exterior.coords)
        exterior_x = [coordinate[0] for coordinate in exterior_coordinates]
        exterior_y = [coordinate[1] for coordinate in exterior_coordinates]
        axes.plot(exterior_x, exterior_y, marker="o", label=label)

        for interior_ring in geometry.interiors:
            interior_coordinates = list(interior_ring.coords)
            interior_x = [coordinate[0] for coordinate in interior_coordinates]
            interior_y = [coordinate[1] for coordinate in interior_coordinates]
            axes.plot(interior_x, interior_y, marker="o")
        return

    if isinstance(geometry, MultiPolygon):
        first_item = True
        for polygon_geometry in geometry.geoms:
            exterior_coordinates = list(polygon_geometry.exterior.coords)
            exterior_x = [coordinate[0] for coordinate in exterior_coordinates]
            exterior_y = [coordinate[1] for coordinate in exterior_coordinates]
            polygon_label = label if first_item else None
            axes.plot(exterior_x, exterior_y, marker="o", label=polygon_label)
            first_item = False

            for interior_ring in polygon_geometry.interiors:
                interior_coordinates = list(interior_ring.coords)
                interior_x = [coordinate[0] for coordinate in interior_coordinates]
                interior_y = [coordinate[1] for coordinate in interior_coordinates]
                axes.plot(interior_x, interior_y, marker="o")
        return

    if isinstance(geometry, GeometryCollection):
        first_item = True
        for part_geometry in geometry.geoms:
            part_label = label if first_item else None
            _draw_geometry_on_axes(axes, part_geometry, part_label)
            first_item = False
        return

    raise TypeError(f"Unsupported geometry type: {geometry.geom_type}")


def plot_geometries_debug(
    geometries: list[tuple[str, BaseGeometry]],
    title: str = "debug",
) -> None:
    figure, axes = plt.subplots()

    for label, geometry in geometries:
        _draw_geometry_on_axes(axes, geometry, label)

    axes.set_title(title)
    axes.set_aspect("equal")
    axes.grid(True)
    axes.legend()
    plt.show()