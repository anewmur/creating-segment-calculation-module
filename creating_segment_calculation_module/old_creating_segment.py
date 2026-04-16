"""Модуль создания сегментов."""

import json

from nedra_calculate_ontology.ontology_model import File
from nedra_calculate_sdk.calculation_module_services import Storage
from shapely.geometry import Polygon as SPolygon
from shapely.geometry import mapping

from creating_segment_calculation_module.models.creating_segment import CalculationInput
from creating_segment_calculation_module.models.creating_segment import CalculationResult
from creating_segment_calculation_module.models.creating_segment import PolygonValue
from creating_segment_calculation_module.models.creating_segment import Segment
from creating_segment_calculation_module.models.creating_segment import SegmentParameters
from creating_segment_calculation_module.models.creating_segment import SegmentType


ERROR_MESSAGE_1 = 'Не попадают в контур: '
ERROR_MESSAGE_2 = 'Не замкнуты полигоны: '


class ModuleError(Exception):
    """Свой класс для ошибок."""


SEGMENT_TYPES = {segment_type.value for segment_type in SegmentType}


def creating_segment(input_data: CalculationInput, storage: 'Storage') -> CalculationResult:
    """Основная функция модуля по созданию сегментов."""
    with open(input_data.parameter.segment.border_model.file.path, encoding='utf-8') as f:
        border_model = create_shapely_polygon(json.load(f)['lines'][0]['points'])

    polygons = []
    result = {}
    validation_error = []
    for index, polygon in enumerate(input_data.polygon):
        with open(polygon.value.file.path, encoding='utf-8') as f:
            data = json.load(f)
            if data['lines'][0]['points'][0] != data['lines'][0]['points'][-1]:
                name = polygon.name
                if not name:
                    name = f'Полигон {index + 1}'
                validation_error.append(name)
            polygons.append(create_shapely_polygon(data['lines'][0]['points']))

    if validation_error:
        raise ModuleError(ERROR_MESSAGE_2 + ' '.join(validation_error))

    for index, polygon in enumerate(polygons):
        new_polygon = border_model.intersection(polygon)
        if new_polygon.wkt == 'POLYGON EMPTY':
            name = input_data.polygon[index].name
            if not name:
                name = f'Полигон {index + 1}'
            validation_error.append(name)
        else:
            result[index] = new_polygon

    if validation_error:
        raise ModuleError(ERROR_MESSAGE_1 + ' '.join(validation_error))

    return result_generation(polygons, input_data.parameter.segment, storage)


def create_shapely_polygon(list_points: dict) -> SPolygon:
    """Функция для создания шейпли полигона из точек."""
    temporary_list = []
    for point in list_points:
        temporary_list.append((point['x'], point['y']))
    return SPolygon(temporary_list)


def result_generation(polygons, parameters: SegmentParameters, storage: 'Storage') -> CalculationResult:
    """Генерируем результат модуля."""
    result = []
    segment_type = parameters.segment_type if parameters.segment_type in SEGMENT_TYPES else SegmentType.general.value

    if parameters.unite:
        temp: dict[str, list] = {'lines': []}
        for polygon in polygons:
            temp['lines'].append({'points': from_shapely_point_to_dict(polygon)})
        result.append(save_segment(temp, segment_type, parameters.segment_name, storage))
    else:
        for polygon in polygons:
            name = parameters.segment_name
            temp = {'lines': [{'points': from_shapely_point_to_dict(polygon)}]}
            result.append(save_segment(temp, segment_type, name, storage))

    return CalculationResult(polygon=result)


def from_shapely_point_to_dict(shapely_polygon: SPolygon) -> list:
    """Функция преобразования точек полигона шейпли в словарь."""
    polygon = []
    for point in mapping(shapely_polygon)['coordinates'][0]:
        polygon.append({'x': point[0], 'y': point[1]})
    return polygon


def save_segment(data: dict, segment_type: str, name: str, storage: 'Storage') -> Segment:
    """Сохранение сегмента."""
    result_file_path = storage.get_temp_dir() / f'{name}_{segment_type}.json'
    with open(result_file_path, 'w') as f:
        f.write(json.dumps(data))
    return Segment(name=name, type=segment_type, value=PolygonValue(file=File(path=str(result_file_path))))
