from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path
import math


def _load_visualizer_module():
    module_path = Path("tests/viz_test/polygon_visualizer_svg.py")
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


def test_rendered_html_uses_single_js_source_for_grid_y_math():
    module = _load_visualizer_module()
    html = module.PolygonVisualizerSVG()._render_html()

    # Grid Y math is centralized in JS helpers.
    assert "function computeGridStep(viewW, viewH)" in html
    assert "function computeGridYLines(viewY, viewH, currentFlipOffset, step)" in html
    assert "const step = computeGridStep(vb.w, vb.h);" in html
    assert "const yLines = computeGridYLines(vb.y, vb.h, flipOffset, step);" in html
    assert "const count = Math.round((yEnd - yStart) / step);" in html
    assert "for (let idx = 0; idx <= count; idx += 1)" in html
    assert re.search(r"mathY\.toFixed\(0\)", html)

    # Old duplicated inline branch/loop code must not return.
    assert "for (let gy = yStart; gy <= yEnd; gy += step)" not in html
    assert "lbl.textContent = (flipOffset - gy).toFixed(0);" not in html


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
