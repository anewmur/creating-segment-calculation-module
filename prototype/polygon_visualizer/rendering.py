import html
import json
from pathlib import Path

from shapely.geometry import Polygon

ASSETS_DIR = Path(__file__).parent / "assets"


def _load_asset(name: str) -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8")


def ring_to_path(coords: list[tuple[float, float]]) -> str:
    if not coords:
        return ""
    segments = [f"M {coords[0][0]},{coords[0][1]}"]
    for x, y in coords[1:]:
        segments.append(f"L {x},{y}")
    segments.append("Z")
    return " ".join(segments)


def polygon_to_svg_path(polygon) -> str:
    parts: list[str] = []

    exterior = list(polygon.exterior.coords)
    parts.append(
        "M " + " L ".join(f"{x} {y}" for x, y in exterior) + " Z"
    )

    for interior in polygon.interiors:
        hole = list(interior.coords)
        parts.append(
            "M " + " L ".join(f"{x} {y}" for x, y in hole) + " Z"
        )

    return " ".join(parts)


def render_svg_layers(layers, bounds, labels_out: list[str]) -> str:
    parts: list[str] = []
    labels_out.clear()

    min_x, min_y, max_x, max_y = bounds
    map_size = max(max_x - min_x, max_y - min_y) or 100
    font_size = map_size * 0.017
    auto_vertex_radius = map_size * 0.012
    flip_offset = min_y + max_y

    for layer_idx, layer in enumerate(layers):
        style = layer.style
        vertex_radius = auto_vertex_radius if style.vertex_radius < 0 else style.vertex_radius
        group_id = f"layer-{layer_idx}"
        parts.append(f'<g id="{group_id}" class="poly-layer">')

        for poly_idx, poly in enumerate(layer.polygons):
            path_d = polygon_to_svg_path(poly)
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

            if vertex_radius > 0:
                vertex_color = style.vertex_color or style.stroke
                for coord_x, coord_y in poly.exterior.coords:
                    parts.append(
                        f'  <circle cx="{coord_x}" cy="{coord_y}" r="{vertex_radius}" '
                        f'fill="{vertex_color}" class="vertex"'
                        f' data-base-r="{vertex_radius}">'
                        f"<title>({coord_x:.2f}, {coord_y:.2f})</title></circle>"
                    )

            if style.label:
                representative_point = poly.representative_point()
                label_y_screen = flip_offset - representative_point.y
                labels_out.append(
                    f'  <text x="{representative_point.x}" y="{label_y_screen}" class="poly-label"'
                    f' fill="{style.stroke}"'
                    f' data-base-font-size="{font_size:.1f}"'
                    f' data-base-y="{label_y_screen}"'
                    f' data-layer="{layer_idx}">'
                    f'{html.escape(label)}</text>'
                )

        parts.append("</g>")

    return "\n".join(parts)


def render_html(layers, title, labels_out, merge_radius: float = 20.0) -> str:
    template_html = _load_asset("template.html")
    inline_css = _load_asset("styles.css")
    inline_js = _load_asset("viewer.js")

    from .geometry import compute_bounds

    min_x, min_y, max_x, max_y = compute_bounds(layers)
    w = max_x - min_x or 100
    h = max_y - min_y or 100
    pad = max(w, h) * 0.06
    vb_x = min_x - pad
    vb_y = min_y - pad
    vb_w = w + 2 * pad
    vb_h = h + 2 * pad

    svg_layers = render_svg_layers(layers, (min_x, min_y, max_x, max_y), labels_out)
    svg_labels = "\n".join(labels_out)
    title_escaped = html.escape(title) if title else ""

    # Контракт данных для JS (window.__VIZ_DATA__) должен быть синхронизирован
    # с prototype/polygon_visualizer/assets/viewer.js.
    viz_data_json = json.dumps(
        {
            "vb": {"x": vb_x, "y": vb_y, "w": vb_w, "h": vb_h},
            "flipOffset": min_y + max_y,
            "worldMinY": min_y,
            "worldMaxY": max_y,
            # Явно передаём mergeRadius как часть контракта между Python и JS.
            "mergeRadius": merge_radius,
        }
    )

    return template_html.format(
        title=title_escaped,
        vb_x=vb_x,
        vb_y=vb_y,
        vb_w=vb_w,
        vb_h=vb_h,
        svg_layers=svg_layers,
        svg_labels=svg_labels,
        inline_css=inline_css,
        viz_data_json=viz_data_json,
        inline_js=inline_js,
    )
