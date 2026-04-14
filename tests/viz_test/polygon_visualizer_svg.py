"""Векторный визуализатор полигонов.

Генерирует интерактивный HTML-файл с SVG-графикой.
Поддерживает зум колёсиком, перетаскивание, тултипы с координатами.
Мелкие пересечения видны при любом увеличении.
"""

import webbrowser
from shapely.algorithms.polylabel import polylabel
import html
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon


@dataclass
class PolygonStyle:
    stroke: str = "#3b82f6"
    stroke_width: float = 1.5
    fill: str = "none"
    fill_opacity: float = 0.2
    vertex_radius: float = 6.0
    vertex_color: str | None = None  # None → same as stroke
    label: str | None = None


@dataclass
class _Layer:
    polygons: list[Polygon]
    style: PolygonStyle


class PolygonVisualizerSVG:
    """Генерирует интерактивный HTML+SVG для визуализации полигонов."""

    def __init__(self) -> None:
        self._layers: list[_Layer] = []
        self._title: str = ""
        self._labels: list[str] = []

    # ── public API ──────────────────────────────────────────────

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
            vertex_radius=28 if draw_vertices else 0,
            vertex_color="#6b7280",
            label=None,
        )
        after_style = PolygonStyle(
            stroke="#1d4ed8",
            stroke_width=1.8,
            fill="#2563eb",
            fill_opacity=0.20,
            vertex_radius=28 if draw_vertices else 0,
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

    # ── internal ────────────────────────────────────────────────

    def _compute_bounds(self) -> tuple[float, float, float, float]:
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for layer in self._layers:
            for poly in layer.polygons:
                bx0, by0, bx1, by1 = poly.bounds
                min_x = min(min_x, bx0)
                min_y = min(min_y, by0)
                max_x = max(max_x, bx1)
                max_y = max(max_y, by1)
        if min_x == float("inf"):
            return 0, 0, 100, 100
        return min_x, min_y, max_x, max_y

    def _polygon_to_svg_path(self, poly: Polygon) -> str:
        """Exterior + holes → SVG path d attribute."""
        parts: list[str] = []
        # exterior
        coords = list(poly.exterior.coords)
        parts.append(self._ring_to_path(coords))
        # holes
        for interior in poly.interiors:
            parts.append(self._ring_to_path(list(interior.coords)))
        return " ".join(parts)

    @staticmethod
    def _ring_to_path(coords: list[tuple[float, float]]) -> str:
        if not coords:
            return ""
        segments = [f"M {coords[0][0]},{coords[0][1]}"]
        for x, y in coords[1:]:
            segments.append(f"L {x},{y}")
        segments.append("Z")
        return " ".join(segments)

    @staticmethod
    def _compute_grid_step(view_width: float, view_height: float, target_lines: int = 12) -> float:
        raw_step = max(view_width, view_height) / target_lines
        power = math.floor(math.log10(raw_step))
        base = 10**power
        ratio = raw_step / base

        if ratio > 5:
            return 10 * base
        if ratio > 2:
            return 5 * base
        if ratio > 1:
            return 2 * base
        return base

    @staticmethod
    def _compute_grid_y_lines(
        view_y: float,
        view_height: float,
        flip_offset: float,
        step: float,
    ) -> list[tuple[float, float]]:
        """Возвращает пары (math_y, svg_y) для горизонтальных линий сетки."""
        math_y_min = flip_offset - (view_y + view_height)
        math_y_max = flip_offset - view_y
        y_start = math.floor(math_y_min / step) * step
        y_end = math.ceil(math_y_max / step) * step

        count = int(round((y_end - y_start) / step))
        lines: list[tuple[float, float]] = []
        for idx in range(count + 1):
            math_y = y_start + idx * step
            lines.append((math_y, flip_offset - math_y))
        return lines

    def _render_svg_layers(self, pad: float) -> str:
        parts: list[str] = []
        self._labels: list[str] = []

        min_x, min_y, max_x, max_y = self._compute_bounds()
        map_size = max(max_x - min_x, max_y - min_y) or 100
        font_size = map_size * 0.017
        flip_offset = min_y + max_y

        for layer_idx, layer in enumerate(self._layers):
            style = layer.style
            group_id = f"layer-{layer_idx}"
            parts.append(f'<g id="{group_id}" class="poly-layer">')

            for poly_idx, poly in enumerate(layer.polygons):
                path_d = self._polygon_to_svg_path(poly)
                fill = style.fill if style.fill != "none" else "none"
                label = f"{style.label}_{poly_idx + 1}" if style.label else f"poly_{poly_idx + 1}"
                tooltip = html.escape(label)

                parts.append(
                    f'  <path d="{path_d}" '
                    f'stroke="{style.stroke}" stroke-width="{style.stroke_width}" '
                    f'fill="{fill}" fill-opacity="{style.fill_opacity}" '
                    f'fill-rule="evenodd" '
                    f'vector-effect="non-scaling-stroke">'
                    f"<title>{tooltip}</title></path>"
                )

                if style.vertex_radius > 0:
                    vertex_color = style.vertex_color or style.stroke
                    for coord_x, coord_y in poly.exterior.coords:
                        parts.append(
                            f'  <circle cx="{coord_x}" cy="{coord_y}" r="{style.vertex_radius}" '
                            f'fill="{vertex_color}" class="vertex"'
                            f' data-base-r="{style.vertex_radius}">'
                            f"<title>({coord_x:.2f}, {coord_y:.2f})</title></circle>"
                        )

                if style.label:
                    representative_point = poly.representative_point()
                    label_y_screen = flip_offset - representative_point.y
                    self._labels.append(
                        f'  <text x="{representative_point.x}" y="{label_y_screen}" class="poly-label"'
                        f' fill="{style.stroke}"'
                        f' data-base-font-size="{font_size:.1f}"'
                        f' data-base-y="{label_y_screen}"'
                        f' data-layer="{layer_idx}">'
                        f'{html.escape(label)}</text>'
                    )

            parts.append("</g>")

        return "\n".join(parts)
    def _render_html(self) -> str:
        min_x, min_y, max_x, max_y = self._compute_bounds()
        w = max_x - min_x or 100
        h = max_y - min_y or 100
        pad = max(w, h) * 0.06
        vb_x = min_x - pad
        vb_y = min_y - pad
        vb_w = w + 2 * pad
        vb_h = h + 2 * pad

        svg_layers = self._render_svg_layers(pad)
        svg_labels = "\n".join(self._labels)
        title_escaped = html.escape(self._title) if self._title else ""

        return _HTML_TEMPLATE.format(
            title=title_escaped,
            vb_x=vb_x,
            vb_y=vb_y,
            vb_w=vb_w,
            vb_h=vb_h,
            min_x=min_x,
            max_x=max_x,
            min_y=min_y,
            max_y=max_y,
            pad=pad,
            svg_layers=svg_layers,
            svg_labels=svg_labels,
        )
    def show(self, path: str | Path) -> None:
        """Сохраняет и открывает в браузере."""
        self.save(path)
        webbrowser.open(Path(path).resolve().as_uri())


# ── HTML template ───────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  
body {{
  background: #dcfce7;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  color: #14532d;
  overflow: hidden;
  height: 100vh;
}}
#header {{
  position: fixed; top: 0; left: 0; right: 0;
  height: 44px;
  background: #bbf7d0;
  border-bottom: 1px solid #86efac;
  display: flex; align-items: center;
  padding: 0 16px;
  z-index: 10;
  gap: 16px;
}}

#header h1 {{
  font-size: 14px;
  font-weight: 600;
  color: #000000;
  white-space: nowrap;
}}
#coords {{
  font-size: 12px;
  color: #000000;
  margin-left: auto;
}}
#zoom-info {{
  font-size: 12px;
  color: #000000;
}}

#controls button {{
  background: #f0fdf4;
  border: 1px solid #000000;
  color: #000000;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
}}
#controls button:hover {{ background: #dcfce7; }}

.grid-line {{
  stroke: #000000;
  stroke-width: 0.5;
  vector-effect: non-scaling-stroke;
}}
.grid-label {{
  font-size: 11px;
  fill: #000000;
  font-family: 'JetBrains Mono', monospace;
}}

.vertex {{
  vector-effect: non-scaling-stroke;
  stroke: #dcfce7;
  stroke-width: 1;
  pointer-events: all;
}}
#legend {{
  position: fixed;
  bottom: 12px; left: 12px;
  background: #f0fdf4dd;
  border: 1px solid #86efac;
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  z-index: 10;
}}


#svg-container {{
    position: fixed;
    top: 44px; left: 0; right: 0; bottom: 0;
    cursor: grab;
}}
#svg-container.dragging {{ cursor: grabbing; }}
svg {{
    width: 100%;
    height: 100%;
    display: block;
}}
#controls {{
    display: flex; gap: 6px;
}}
.poly-layer path {{
    transition: fill-opacity 0.15s;
}}
.poly-layer path:hover {{
    fill-opacity: 0.45 !important;
    stroke-width: 2.5;
}}
.vertex:hover {{
    r: 5;
    fill: #f59e0b !important;
}}
.poly-label {{
    font-family: 'JetBrains Mono', monospace;
    text-anchor: middle;
    dominant-baseline: central;
    pointer-events: none;
}}
  .legend-item {{
    display: flex; align-items: center; gap: 8px;
  }}
  .legend-swatch {{
    width: 18px; height: 4px;
    border-radius: 2px;
  }}
  /* Y‑axis is flipped in SVG (we keep math coords) */
</style>
</head>
<body>

<div id="header">
  <h1>{title}</h1>
  <div id="controls">
    <button onclick="resetView()">Сброс</button>
    <button onclick="zoomIn()">+</button>
    <button onclick="zoomOut()">−</button>
  </div>
  <span id="zoom-info">100%</span>
  <span id="coords">—</span>
</div>

<div id="svg-container">
<svg id="canvas" viewBox="{vb_x} {vb_y} {vb_w} {vb_h}"
     xmlns="http://www.w3.org/2000/svg"
     preserveAspectRatio="xMidYMid meet">
  <!-- flip Y so math coords go up -->
  <g id="world" transform="scale(1,-1) translate(0, 0)">
      <g id="grid"></g>
      {svg_layers}
  </g>
  <!-- Подписи без отражения, чтобы текст не переворачивался -->
  <g id="labels">
      <g id="grid-labels"></g>
      {svg_labels}
  </g>
</svg>
</div>

<div id="legend" id="legend"></div>

<script>
(function() {{
  const svg   = document.getElementById('canvas');
  const cont  = document.getElementById('svg-container');
  const info  = document.getElementById('zoom-info');
  const coord = document.getElementById('coords');

  // initial viewBox
  const VB0 = {{ x: {vb_x}, y: {vb_y}, w: {vb_w}, h: {vb_h} }};
  let vb = {{ ...VB0 }};
  const WORLD_MIN_Y = {min_y};
  const WORLD_MAX_Y = {max_y};
  const flipOffset  = WORLD_MIN_Y + WORLD_MAX_Y;

  // set flip offset
  document.getElementById('world')
    .setAttribute('transform', `scale(1,-1) translate(0, -${{flipOffset}})`);
    
function applyVB() {{
  svg.setAttribute('viewBox', `${{vb.x}} ${{vb.y}} ${{vb.w}} ${{vb.h}}`);
  info.textContent = Math.round(VB0.w / vb.w * 100) + '%';
  drawGrid();
  updateLabelScale();
}}

function updateLabelScale() {{
  const zoom = VB0.w / vb.w;
  const labels = document.querySelectorAll('#labels .poly-label');

  labels.forEach(label => {{
    const baseFontSize = Number(label.dataset.baseFontSize || 12);
    const fontSize = zoom >= 1 ? baseFontSize / zoom : baseFontSize;
    const baseY = Number(label.dataset.baseY);
    const layerIdx = Number(label.dataset.layer || 0);
    const offset = layerIdx * fontSize * 2;

    label.setAttribute('font-size', String(fontSize));
    label.setAttribute('y', String(baseY - offset));
  }});

  const vertices = document.querySelectorAll('.vertex');
  vertices.forEach(v => {{
    const baseR = Number(v.dataset.baseR || 3);
    const r = zoom >= 1 ? baseR / zoom : baseR;
    v.setAttribute('r', String(r));
  }});
}}

function computeGridStep(viewW, viewH) {{
  const targetLines = 12;
  const rawStep = Math.max(viewW, viewH) / targetLines;
  const power = Math.floor(Math.log10(rawStep));
  const base = 10 ** power;
  if (rawStep / base > 5) return 10 * base;
  if (rawStep / base > 2) return 5 * base;
  if (rawStep / base > 1) return 2 * base;
  return base;
}}

function computeGridYLines(viewY, viewH, currentFlipOffset, step) {{
  const mathYMin = currentFlipOffset - (viewY + viewH);
  const mathYMax = currentFlipOffset - viewY;
  const yStart = Math.floor(mathYMin / step) * step;
  const yEnd = Math.ceil(mathYMax / step) * step;

  const lines = [];
  const count = Math.round((yEnd - yStart) / step);
  for (let idx = 0; idx <= count; idx += 1) {{
    const mathY = yStart + idx * step;
    lines.push({{ mathY, svgY: currentFlipOffset - mathY }});
  }}
  return lines;
}}

function drawGrid() {{
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  const gridLabels = document.getElementById('grid-labels');
  gridLabels.innerHTML = '';

  const GRID_OVERSCAN_FACTOR = 10;
  const step = computeGridStep(vb.w, vb.h);
  const fontSize = Math.min(vb.w, vb.h) * 0.022;
  const visibleYLines = computeGridYLines(vb.y, vb.h, flipOffset, step);

  // Overscan only for grid lines (continuous infinite-like grid effect).
  const gridMinX = vb.x - vb.w * GRID_OVERSCAN_FACTOR;
  const gridMaxX = vb.x + vb.w + vb.w * GRID_OVERSCAN_FACTOR;
  const gridMinY = vb.y - vb.h * GRID_OVERSCAN_FACTOR;
  const gridMaxY = vb.y + vb.h + vb.h * GRID_OVERSCAN_FACTOR;

  const mathGridYMin = flipOffset - gridMaxY;
  const mathGridYMax = flipOffset - gridMinY;
  const overscannedYLines = computeGridYLines(gridMinY, gridMaxY - gridMinY, flipOffset, step);

  const xStart = Math.floor(gridMinX / step) * step;
  const xEnd = Math.ceil(gridMaxX / step) * step;
  const labelXStart = Math.floor(vb.x / step) * step;
  const labelXEnd = Math.ceil((vb.x + vb.w) / step) * step;

  for (let gx = xStart; gx <= xEnd; gx += step) {{
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', gx);
    line.setAttribute('y1', mathGridYMin);
    line.setAttribute('x2', gx);
    line.setAttribute('y2', mathGridYMax);
    line.setAttribute('class', 'grid-line');
    grid.appendChild(line);
  }}

  for (let gx = labelXStart; gx <= labelXEnd; gx += step) {{
    const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    lbl.setAttribute('x', gx);
    lbl.setAttribute('y', vb.y + fontSize * 1.2);
    lbl.setAttribute('text-anchor', 'middle');
    lbl.setAttribute('font-size', fontSize);
    lbl.setAttribute('class', 'grid-label');
    lbl.textContent = gx.toFixed(0);
    gridLabels.appendChild(lbl);
  }}

  for (const {{ mathY }} of overscannedYLines) {{
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', gridMinX);
    line.setAttribute('y1', mathY);
    line.setAttribute('x2', gridMaxX);
    line.setAttribute('y2', mathY);
    line.setAttribute('class', 'grid-line');
    grid.appendChild(line);
  }}

  for (const {{ mathY, svgY }} of visibleYLines) {{
    const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    lbl.setAttribute('x', vb.x + fontSize * 0.3);
    lbl.setAttribute('y', svgY - fontSize * 0.3);
    lbl.setAttribute('font-size', fontSize);
    lbl.setAttribute('class', 'grid-label');
    lbl.textContent = mathY.toFixed(0);
    gridLabels.appendChild(lbl);
  }}
}}

  // ── mouse zoom ──
  cont.addEventListener('wheel', e => {{
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    const rect = svg.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top)  / rect.height;
    const nw = vb.w * factor;
    const nh = vb.h * factor;
    vb.x += (vb.w - nw) * mx;
    vb.y += (vb.h - nh) * my;
    vb.w = nw;
    vb.h = nh;
    applyVB();
  }}, {{ passive: false }});

  // ── drag ──
  let dragging = false, lastX, lastY;
  cont.addEventListener('mousedown', e => {{
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    cont.classList.add('dragging');
  }});
  window.addEventListener('mousemove', e => {{
    if (!dragging) return;
    const rect = svg.getBoundingClientRect();
    const dx = (e.clientX - lastX) / rect.width  * vb.w;
    const dy = (e.clientY - lastY) / rect.height * vb.h;
    vb.x -= dx; vb.y -= dy;
    lastX = e.clientX; lastY = e.clientY;
    applyVB();
  }});
  window.addEventListener('mouseup', () => {{
    dragging = false;
    cont.classList.remove('dragging');
  }});

  // ── coords display ──
  svg.addEventListener('mousemove', e => {{
    const pt  = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
    // undo flip
    const worldX = svgP.x;
    const worldY = flipOffset - svgP.y;
    coord.textContent = `x: ${{worldX.toFixed(2)}}  y: ${{worldY.toFixed(2)}}`;
  }});

  // ── buttons ──
  window.resetView = () => {{ vb = {{ ...VB0 }}; applyVB(); }};
  window.zoomIn    = () => {{
    vb.x += vb.w * 0.15; vb.y += vb.h * 0.15;
    vb.w *= 0.7; vb.h *= 0.7; applyVB();
  }};
  window.zoomOut   = () => {{
    vb.x -= vb.w * 0.2; vb.y -= vb.h * 0.2;
    vb.w *= 1.4; vb.h *= 1.4; applyVB();
  }};

  applyVB();

// ── legend ──
  const legend = document.getElementById('legend');
  const seenNames = new Set();
  const labelEls = document.querySelectorAll('#labels .poly-label');
  labelEls.forEach(label => {{
    const color = label.getAttribute('fill');
    const rawText = label.textContent;
    const name = rawText.replace(/_\\d+$/, '');
    if (seenNames.has(name)) return;
    seenNames.add(name);
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.innerHTML = `<span class="legend-swatch" style="background:${{color}}"></span>${{name}}`;
    legend.appendChild(item);
  }});
  
  
}})();
</script>
</body>
</html>
"""
