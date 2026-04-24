

import json
from pathlib import Path


SEPARATOR_VALUE = 999.0


def is_separator(values: list[float]) -> bool:
    return (
        len(values) == 3
        and values[0] == SEPARATOR_VALUE
        and values[1] == SEPARATOR_VALUE
        and values[2] == SEPARATOR_VALUE
    )


def parse_triplet(line: str) -> list[float] | None:
    stripped = line.strip()
    if not stripped:
        return None

    parts = stripped.split()
    if len(parts) != 3:
        raise ValueError(f'Ожидалось 3 числа в строке, получено {len(parts)}: {line!r}')

    return [float(parts[0]), float(parts[1]), float(parts[2])]


def is_closed(points: list[dict[str, float]]) -> bool:
    if len(points) < 4:
        return False

    first_point = points[0]
    last_point = points[-1]
    return first_point['x'] == last_point['x'] and first_point['y'] == last_point['y']


def txt_to_lines(txt_path: Path) -> list[dict[str, list[dict[str, float]]]]:
    result_lines: list[dict[str, list[dict[str, float]]]] = []
    current_points: list[dict[str, float]] = []

    content = txt_path.read_text(encoding='utf-8')

    for raw_line in content.splitlines():
        triplet = parse_triplet(raw_line)
        if triplet is None:
            continue

        if is_separator(triplet):
            if current_points and is_closed(current_points):
                result_lines.append({'points': list(current_points)})
            current_points = []
            continue

        point = {'x': triplet[0], 'y': triplet[1]}
        current_points.append(point)

    if current_points and is_closed(current_points):
        result_lines.append({'points': list(current_points)})

    return result_lines


def convert_txt_polygon_to_json(txt_path: str | Path, json_path: str | Path) -> None:
    txt_file = Path(txt_path)
    json_file = Path(json_path)

    polygon_data = {'lines': txt_to_lines(txt_file)}
    json_file.write_text(
        json.dumps(polygon_data, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def main() -> None:
    txt_path = Path('..\data\polygon3.txt')
    json_path = Path('..\data\polygon3.json')
    convert_txt_polygon_to_json(txt_path, json_path)
    print(f'Готово: {json_path}')

    # import os
    # arr = os.listdir('..\data')
    # print(arr)


if __name__ == '__main__':
    main()