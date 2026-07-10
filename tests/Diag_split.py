"""Диагностика: разрежется ли зона перекрытия одной прямой между двумя общими точками.

Воспроизводит ровно то, что делает TwoPointsOverlapHandler, но без прода:
берёт два полигона, находит overlap и две общие граничные точки, строит
отрезок между ними, режет overlap этим отрезком и печатает результат.

Использование:
    1. Вставь WKT двух полигонов в POLY_I_WKT / POLY_J_WKT ниже.
    2. python diag_split.py
"""

from shapely import wkt
from shapely.geometry import LineString
from shapely.geometry import Point
from shapely.ops import split


# ------------------------------------------------------------------
# ВСТАВЬ СЮДА WKT из отладчика:
#     print(repr(first_polygon.wkt))
#     print(repr(second_polygon.wkt))
# ------------------------------------------------------------------
POLY_I_WKT = "POLYGON ((634222.7418339633 7088537.154886367, 634222.7418339633 7084334.832726044, 636885.9969610593 7084401.748684004, 636725.3986619209 7088644.2204190865, 634222.7418339633 7088537.154886367))"
POLY_J_WKT = "POLYGON ((634835.1880996355 7087689.273153783, 634811.9209821173 7087910.644989651, 634743.1365142461 7088122.341814031, 634631.8409073326 7088315.111459864, 634482.8983134544 7088480.528968616, 634302.8182386697 7088611.364801394, 634099.4710463667 7088701.900804484, 633881.7439846173 7088748.180120112, 633659.1527707903 7088748.180120112, 633441.4257090408 7088701.900804484, 633238.0785167379 7088611.364801394, 633057.9984419532 7088480.528968616, 632909.055848075 7088315.111459864, 632797.7602411614 7088122.341814031, 632728.9757732903 7087910.644989651, 632705.708655772 7087689.273153783, 632728.9757732903 7087467.901317915, 632797.7602411614 7087256.204493535, 632909.055848075 7087063.434847701, 633057.9984419532 7086898.017338949, 633238.0785167379 7086767.181506172, 633441.4257090408 7086676.645503081, 633659.1527707903 7086630.366187453, 633881.7439846173 7086630.366187453, 634099.4710463667 7086676.645503081, 634302.8182386697 7086767.181506172, 634482.8983134544 7086898.017338949, 634631.8409073326 7087063.434847701, 634743.1365142461 7087256.204493535, 634811.9209821173 7087467.901317915, 634835.1880996355 7087689.273153783))"

# Допуск, с которым классификатор считает точку лежащей на границе.
BOUNDARY_TOLERANCE = 1e-9
# Порог «нулевой» площади из constants.py.
BOUNDARY_TOUCH_AREA_TOLERANCE = 1e-5


def point_on_boundary(polygon, point, tolerance=BOUNDARY_TOLERANCE):
    """Лежит ли точка на границе полигона (в пределах допуска)."""
    return polygon.boundary.buffer(tolerance).covers(point)


def find_shared_boundary_vertices(overlap, poly_i, poly_j):
    """Находит вершины overlap, лежащие на границе ОБОИХ полигонов."""
    shared = []
    inside = []
    for coord_x, coord_y in overlap.exterior.coords[:-1]:
        point = Point(coord_x, coord_y)
        on_i = point_on_boundary(poly_i, point)
        on_j = point_on_boundary(poly_j, point)
        if on_i and on_j:
            shared.append((coord_x, coord_y))
        else:
            inside.append((coord_x, coord_y))
    return shared, inside


def distance_point_to_segment(point_xy, seg_start, seg_end):
    """Расстояние от точки до прямого отрезка."""
    segment = LineString([seg_start, seg_end])
    return segment.distance(Point(point_xy))


def main():
    poly_i = wkt.loads(POLY_I_WKT)
    poly_j = wkt.loads(POLY_J_WKT)

    print("=== Входные полигоны ===")
    print(f"poly_i: valid={poly_i.is_valid}, area={poly_i.area:.6f}, "
          f"вершин={len(poly_i.exterior.coords) - 1}")
    print(f"poly_j: valid={poly_j.is_valid}, area={poly_j.area:.6f}, "
          f"вершин={len(poly_j.exterior.coords) - 1}")

    overlap = poly_i.intersection(poly_j)
    print("\n=== Зона перекрытия (overlap) ===")
    print(f"geom_type={overlap.geom_type}, valid={overlap.is_valid}, "
          f"empty={overlap.is_empty}, area={overlap.area:.6f}")

    if overlap.geom_type != "Polygon":
        print("!! overlap не Polygon — это уже не block-4-подобный случай, дальше нет смысла.")
        return

    print(f"вершин у overlap = {len(overlap.exterior.coords) - 1}")

    shared, inside = find_shared_boundary_vertices(overlap, poly_i, poly_j)
    print("\n=== Классификация вершин overlap ===")
    print(f"общих граничных вершин (shared) = {len(shared)}")
    print(f"внутренних вершин (inside)      = {len(inside)}")
    for point in shared:
        print(f"  shared:  ({point[0]:.4f}, {point[1]:.4f})")

    if len(shared) != 2:
        print(f"\n!! Общих точек не 2, а {len(shared)}. "
              f"Условие 'разрез между двумя точками' неприменимо.")
        return

    # --- Ключевой вопрос 1: на одной ли границе все внутренние вершины? ---
    print("\n=== Вопрос 1: где лежат внутренние вершины ===")
    on_i_count = 0
    on_j_count = 0
    for point_xy in inside:
        point = Point(point_xy)
        if point_on_boundary(poly_i, point):
            on_i_count += 1
        if point_on_boundary(poly_j, point):
            on_j_count += 1
    print(f"внутренних вершин на границе poly_i = {on_i_count}")
    print(f"внутренних вершин на границе poly_j = {on_j_count}")
    if on_i_count == len(inside) and on_j_count == 0:
        print("-> все внутренние лежат на границе poly_i (дуга одного полигона)")
    elif on_j_count == len(inside) and on_i_count == 0:
        print("-> все внутренние лежат на границе poly_j (дуга одного полигона)")
    else:
        print("-> внутренние вершины ВПЕРЕМЕШКУ — это не одна дуга")

    # --- Ключевой вопрос 2: отстоят ли внутренние от прямого отрезка? ---
    first_vertex, second_vertex = shared[0], shared[1]
    print("\n=== Вопрос 2: расстояние внутренних вершин до прямого отрезка ===")
    max_dist = 0.0
    for point_xy in inside:
        dist = distance_point_to_segment(point_xy, first_vertex, second_vertex)
        max_dist = max(max_dist, dist)
    print(f"макс. расстояние внутренней вершины до отрезка = {max_dist:.6f}")
    if max_dist < BOUNDARY_TOLERANCE:
        print("-> все внутренние лежат НА прямой (разрез действительно прямой)")
    else:
        print("-> внутренние ОТСТОЯТ от прямой (разрез не прямой — это дуга/излом)")

    # --- Ключевой вопрос 3: даст ли split() две половины? ---
    cut_segment = LineString([first_vertex, second_vertex])
    print("\n=== Вопрос 3: результат split(overlap, cut_segment) ===")
    try:
        split_result = split(overlap, cut_segment)
    except Exception as exc:  # noqa: BLE001 — диагностика, хотим видеть любую ошибку
        print(f"!! split бросил исключение: {type(exc).__name__}: {exc}")
        return

    parts = list(split_result.geoms)
    polygon_parts = [g for g in parts
                     if g.geom_type == "Polygon"
                     and g.is_valid
                     and g.area > BOUNDARY_TOUCH_AREA_TOLERANCE]
    print(f"всего частей от split = {len(parts)}")
    print(f"валидных полигональных частей с площадью > порога = {len(polygon_parts)}")
    for idx, part in enumerate(polygon_parts):
        print(f"  часть {idx}: area={part.area:.6f}, "
              f"вершин={len(part.exterior.coords) - 1}")

    print("\n=== Промежуточный вывод по split ===")
    if len(polygon_parts) == 2:
        print("split дал 2 половины -> идём к end-to-end прогону handler.")
    else:
        print(f"split дал {len(polygon_parts)} половин(ы), а нужно 2 -> "
              f"handler вернёт False на split. Дальше нет смысла.")
        return

    # --- Вопрос 4: реальный TwoPointsOverlapHandler.handle end-to-end ---
    # Импорт прода. Если путь другой — поправь строку ниже.
    from creating_segment_calculation_module.intersection_handlers.two_points_overlap_handler import (
        TwoPointsOverlapHandler,
    )
    from creating_segment_calculation_module.constants import BOUNDARY_TOUCH_AREA_TOLERANCE as PROD_AREA_TOL
    from creating_segment_calculation_module.constants import POINT_DEDUP_TOLERANCE
    from creating_segment_calculation_module.constants import SHARED_EDGE_TOLERANCE

    print("\n=== Вопрос 4: реальный TwoPointsOverlapHandler.handle ===")
    handler = TwoPointsOverlapHandler(
        point_dedup_tolerance=POINT_DEDUP_TOLERANCE,
        shared_edge_tolerance=SHARED_EDGE_TOLERANCE,
        boundary_touch_area_tolerance=PROD_AREA_TOL,
    )

    # handle мутирует список на месте — даём копию пары под индексами 0 и 1.
    pair = [poly_i, poly_j]
    result = handler.handle(
        polygons=pair,
        first_index=0,
        second_index=1,
        first_intersection_point=Point(first_vertex),
        second_intersection_point=Point(second_vertex),
    )

    print(f"handle вернул: {result}")
    if not result:
        print("-> handler НЕ перестроил пару. Ослабление классификатора кейс не починит "
              "напрямую — пара уедет в block 5 как fallback (текущее поведение сохранится).")
        return

    new_i, new_j = pair[0], pair[1]
    residual_overlap = new_i.intersection(new_j).area
    original_union = poly_i.union(poly_j).area
    rebuilt_area = new_i.area + new_j.area
    print(f"новый poly_i: area={new_i.area:.6f}, вершин={len(new_i.exterior.coords) - 1}")
    print(f"новый poly_j: area={new_j.area:.6f}, вершин={len(new_j.exterior.coords) - 1}")
    print(f"остаточное наложение новой пары = {residual_overlap:.6f} "
          f"(порог {PROD_AREA_TOL})")
    print(f"площадь: было (union) {original_union:.6f}, стало {rebuilt_area:.6f}, "
          f"разница {abs(rebuilt_area - original_union):.6f}")

    print("\n=== ИТОГ ===")
    if residual_overlap <= PROD_AREA_TOL:
        print("Пара перестроена БЕЗ остаточного наложения. Ослабление классификатора "
              "до shared==2 для этого кейса безопасно и достаточно.")
    else:
        print("!! handle вернул True, но остаточное наложение выше порога — "
              "это уже несогласованность, разбираем отдельно.")


if __name__ == "__main__":
    main()