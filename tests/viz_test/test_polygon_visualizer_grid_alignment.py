from __future__ import annotations

import importlib.util
import math
import re
import sys
import types
from html.parser import HTMLParser
from pathlib import Path


class _SvgStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._stack: list[str] = []
        self.parent_by_id: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        element_id = attrs_dict.get("id")
        current_parent = self._stack[-1] if self._stack else None
        if element_id:
            self.parent_by_id[element_id] = current_parent
        self._stack.append(element_id or "")

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            self._stack.pop()


def _load_visualizer_module():
    module_path = Path(__file__).resolve().parent / "polygon_visualizer_svg.py"
    spec = importlib.util.spec_from_file_location("polygon_visualizer_svg_test", module_path)
    assert spec and spec.loader

    fake_shapely = types.ModuleType("shapely")
    fake_shapely_algorithms = types.ModuleType("shapely.algorithms")
    fake_shapely_polylabel = types.ModuleType("shapely.algorithms.polylabel")
    fake_shapely_geometry = types.ModuleType("shapely.geometry")

    class _FakePolygon:
        pass

    class _FakeMultiPolygon:
        geoms: list = []

    def _fake_polylabel(*_args, **_kwargs):
        return None

    fake_shapely_polylabel.polylabel = _fake_polylabel
    fake_shapely_geometry.Polygon = _FakePolygon
    fake_shapely_geometry.MultiPolygon = _FakeMultiPolygon

    sys.modules.setdefault("shapely", fake_shapely)
    sys.modules.setdefault("shapely.algorithms", fake_shapely_algorithms)
    sys.modules.setdefault("shapely.algorithms.polylabel", fake_shapely_polylabel)
    sys.modules.setdefault("shapely.geometry", fake_shapely_geometry)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rendered_html_places_grid_lines_in_world_and_labels_outside_it():
    module = _load_visualizer_module()
    html = module.PolygonVisualizerSVG()._render_html()

    parser = _SvgStructureParser()
    parser.feed(html)

    parent_by_id = parser.parent_by_id
    assert parent_by_id["world"] == "canvas"
    assert parent_by_id["grid"] == "world"
    assert parent_by_id["labels"] == "canvas"
    assert parent_by_id["grid-labels"] == "labels"


def test_grid_y_behavior_contract_for_initial_zoom_drag():
    module = _load_visualizer_module()
    visualizer = module.PolygonVisualizerSVG()
    min_x, min_y, max_x, max_y = visualizer._compute_bounds()

    w = max_x - min_x
    h = max_y - min_y
    pad = max(w, h) * 0.06
    flip_offset = min_y + max_y

    vb0 = {
        "x": min_x - pad,
        "y": min_y - pad,
        "w": w + 2 * pad,
        "h": h + 2 * pad,
    }
    vb_zoom = {
        "x": vb0["x"] + vb0["w"] * 0.15,
        "y": vb0["y"] + vb0["h"] * 0.15,
        "w": vb0["w"] * 0.7,
        "h": vb0["h"] * 0.7,
    }
    vb_drag = {
        "x": vb_zoom["x"] - vb_zoom["w"] * 0.2,
        "y": vb_zoom["y"] + vb_zoom["h"] * 0.1,
        "w": vb_zoom["w"],
        "h": vb_zoom["h"],
    }

    for vb in (vb0, vb_zoom, vb_drag):
        step = visualizer._compute_grid_step(vb["w"], vb["h"])
        lines = visualizer._compute_grid_y_lines(vb["y"], vb["h"], flip_offset, step)
        assert lines

        visible_math_min = flip_offset - (vb["y"] + vb["h"])
        visible_math_max = flip_offset - vb["y"]
        assert lines[0][0] <= visible_math_min + 1e-9
        assert lines[-1][0] >= visible_math_max - 1e-9

        for idx, (math_y, svg_y) in enumerate(lines):
            assert math.isclose(svg_y, flip_offset - math_y, abs_tol=1e-9)
            if idx > 0:
                prev_math_y, prev_svg_y = lines[idx - 1]
                assert math.isclose(math_y - prev_math_y, step, abs_tol=1e-9)
                assert math.isclose(prev_svg_y - svg_y, step, abs_tol=1e-9)


def test_grid_js_does_not_use_legacy_unflipped_y_loop():
    module = _load_visualizer_module()
    html = module.PolygonVisualizerSVG()._render_html()

    assert "for (let gy = yStart; gy <= yEnd; gy += step)" not in html
    assert "lbl.textContent = (flipOffset - gy).toFixed(0);" not in html

    assert re.search(r"function\s+computeGridYLines\(viewY,\s*viewH,\s*currentFlipOffset,\s*step\)", html)
    assert re.search(r"line\.setAttribute\('y1',\s*mathYMin\)", html)
    assert re.search(r"line\.setAttribute\('y2',\s*mathYMax\)", html)
    assert re.search(r"line\.setAttribute\('y1',\s*mathY\)", html)
    assert re.search(r"line\.setAttribute\('y2',\s*mathY\)", html)
