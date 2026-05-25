from enum import StrEnum

from pydantic import BaseModel
from pydantic import Field

from .creating_segment import PolygonValue


class SEGMENT_TYPE_NAME_ENUM(StrEnum):
    """Перечисление доступных типов для формирования имени сегмента"""

    polygon_name = 'Имени полигона'
    well_name = 'Имени ствола'


class TargetPoint(BaseModel):
    x: float = Field(..., description='Координата X точки')
    y: float = Field(..., description='Координата Y точки')


class Target(BaseModel):
    point: list[TargetPoint] = Field(..., description='Список точек')


class Line(BaseModel):
    """Модель линии, состоящей из последовательности точек"""

    points: list[TargetPoint] = Field(default_factory=list, description='Список точек, формирующих линию')


class PolygonLine(BaseModel):
    """Модель полигона, состоящего из набора линий"""

    lines: list[Line] = Field(default_factory=list, description='Список линий, формирующих полигон')


class Well(BaseModel):
    name: str = Field(..., description='Имя скважины')
    target: Target = Field(..., description='Цель')


class Polygon(BaseModel):
    id: str = Field(..., description='ID полигона')
    name: str = Field(..., description='Имя полигона')
    value: PolygonValue = Field(..., description='Значение полигона')


class FormationInput(BaseModel):
    name: str = Field(..., description='Имя пласта')


class Parameter(BaseModel):
    name_by: SEGMENT_TYPE_NAME_ENUM = Field(..., description='Признак формирования имени сегмента')
    gs_part: float | None = Field(None, description='Процент вхождения ГС в сегмент')
    segments_group: str = Field(..., description='Группа сегментов')
    segments_type: str = Field(..., description='Тип сегментов')
    merge_radius: float = Field(default=20, description='Радиус склейки, м')
    process_intersections: int = Field(
        default=1,
        description='Флаг обработки пересечений: 0 — исключать, 1 — перестраивать',
    )


class FormationModel(BaseModel):
    border_model: PolygonValue = Field(..., description='Контур модели')


class CalculationInput(BaseModel):
    """Входные данные для расчета полигонов Вороного"""

    polygon: Polygon = Field(..., description='Данные полигона')
    well: list[Well] = Field(default_factory=list, description='Список скважин для обработки')
    formation: FormationInput = Field(..., description='Параметры пласта')
    parameter: Parameter = Field(..., description='Параметры расчета')
    formation_model: FormationModel | None = Field(None, description='Модель пласта')


class Segment(BaseModel):
    name: str = Field(..., description='Имя сегмента')
    group: str = Field(..., description='Группа сегментов')
    type: str = Field(..., description='Тип сегмента')
    value: PolygonValue = Field(..., description='Файл сегмента')
    polygon_id: str = Field(..., description='ID полигона, из которого создан сегмент')


class FormationResult(BaseModel):
    segment: list[Segment] = Field(..., description='Группы сегментов')
    name: str = Field(..., description='Имя пласта')


class CalculationResult(BaseModel):
    """Результат расчета полигонов Вороного"""

    formation: FormationResult | None = Field(None, description='Данные созданных сегментов')
    info: list[str] = Field(default_factory=list, description='Информационные сообщения о процессе расчета')
    warning: list[str] = Field(default_factory=list, description='Предупреждающие сообщения о нестандартных ситуациях')
    error: list[str] = Field(default_factory=list, description='Сообщения об ошибках, прервавших расчет')
