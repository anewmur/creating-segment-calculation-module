import webbrowser
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon

from .geometry import compute_bounds, compute_grid_step, compute_grid_y_lines
from .rendering import render_html, render_svg_layers


@dataclass
class PolygonStyle:
    stroke: str = "#3b82f6"
    stroke_width: float = 1.5
    fill: str = "none"
    fill_opacity: float = 0.2
    vertex_radius: float = 4.0
    vertex_color: str | None = None
    label: str | None = None


@dataclass
class _Layer:
    polygons: list[Polygon]
    style: PolygonStyle


class PolygonVisualizerSVG:
    """Генерирует интерактивный HTML+SVG для визуализации полигонов."""

    def __init__(self, merge_radius: float = 20.0) -> None:
        self._layers: list[_Layer] = []
        self._title: str = ""
        self._labels: list[str] = []
        self._merge_radius = merge_radius

    def draw_polygons(
        self,
        polygons: list[Polygon],
        style: PolygonStyle | None = None,
    ) -> None:
        if style is None:
            style = PolygonStyle()
        flat: list[Polygon] = []
        for p in polygons:
            if isinstance(p, MultiPolygon):
                flat.extend(p.geoms)
            else:
                flat.append(p)
        self._layers.append(_Layer(polygons=flat, style=style))

    def draw_before_after(
        self,
        before: list[Polygon],
        after: list[Polygon],
        draw_vertices: bool = True,
    ) -> None:
        before_style = PolygonStyle(
            stroke="#6b7280",
            stroke_width=1.0,
            fill="#9ca3af",
            fill_opacity=0.16,
            vertex_radius=0.75 if draw_vertices else 0,
            vertex_color="#6b7280",
            label=None,
        )
        after_style = PolygonStyle(
            stroke="#1d4ed8",
            stroke_width=1.8,
            fill="#2563eb",
            fill_opacity=0.20,
            vertex_radius=0.75 if draw_vertices else 0,
            vertex_color="#1d4ed8",
            label=None,
        )
        self.draw_polygons(before, before_style)
        self.draw_polygons(after, after_style)

    def set_title(self, title: str) -> None:
        self._title = title

    def save(self, output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render_html(), encoding="utf-8")

    def _compute_bounds(self) -> tuple[float, float, float, float]:
        return compute_bounds(self._layers)

    @staticmethod
    def _compute_grid_step(view_width: float, view_height: float, target_lines: int = 12) -> float:
        return compute_grid_step(view_width, view_height, target_lines)

    @staticmethod
    def _compute_grid_y_lines(view_y, view_h, flip_offset, step) -> list[tuple[float, float]]:
        return compute_grid_y_lines(view_y, view_h, flip_offset, step)

    def _render_svg_layers(self, pad: float) -> str:
        _ = pad
        return render_svg_layers(self._layers, self._compute_bounds(), self._labels)

    def _render_html(self) -> str:
        return render_html(self._layers, self._title, self._labels, merge_radius=self._merge_radius)

    def show(self, path: str | Path) -> None:
        self.save(path)
        webbrowser.open(Path(path).resolve().as_uri())
