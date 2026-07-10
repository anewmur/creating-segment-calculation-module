from enum import StrEnum

from creating_segment_calculation_module.models.creating_segment import PolygonValue
from nedra_calculate_sdk.models import BaseCalculationResult
from pydantic import BaseModel
from pydantic import Field


class SEGMENT_TYPE_NAME_ENUM(StrEnum):
    """Перечисление доступных типов для формирования имени сегмента."""
    polygon_name = 'Имени полигона'
    well_name = 'Имени ствола'


class TargetPoint(BaseModel):
    """Точка контура или траектории скважины."""

    x: float = Field(..., description='Координата X точки')
    y: float = Field(..., description='Координата Y точки')


class Target(BaseModel):
    """Целевые точки скважины."""

    point: list[TargetPoint] = Field(..., description='Список точек')


class Line(BaseModel):
    """Линия, состоящая из последовательности точек."""

    points: list[TargetPoint] = Field(default_factory=list, description='Список точек, формирующих линию')


class PolygonLine(BaseModel):
    """Полигон, состоящий из набора линий."""

    lines: list[Line] = Field(default_factory=list, description='Список линий, формирующих полигон')


class Well(BaseModel):
    """Скважина с целевыми точками."""

    name: str = Field(..., description='Имя скважины')
    target: Target = Field(..., description='Цель')


class Polygon(BaseModel):
    """Входной полигон."""

    id: str = Field(..., description='ID полигона')
    name: str = Field(..., description='Имя полигона')
    value: PolygonValue = Field(..., description='Значение полигона')


class FormationInput(BaseModel):
    """Входные данные пласта."""

    name: str = Field(..., description='Имя пласта')


class Parameter(BaseModel):
    """Параметры расчёта сегментов."""

    name_by: SEGMENT_TYPE_NAME_ENUM = Field(..., description='Признак формирования имени сегмента')
    gs_part: float | None = Field(None, description='Процент вхождения ГС в сегмент')
    segments_group: str = Field(..., description='Группа сегментов')
    segments_type: str = Field(..., description='Тип сегментов')
    merge_radius: float = Field(20, description='Радиус склейки, м')
    process_intersections: int = Field(
        default=1,
        description='Флаг обработки пересечений: 0 - исключать, 1 - перестраивать',
    )


class FormationModel(BaseModel):
    """Контур модели пласта."""

    border_model: PolygonValue = Field(..., description='Контур модели')


class CalculationInput(BaseModel):
    """Входные данные для расчёта сегментов."""

    polygon: Polygon = Field(..., description='Данные полигона')
    well: list[Well] = Field(default_factory=list, description='Список скважин для обработки')
    formation: FormationInput = Field(..., description='Параметры пласта')
    parameter: Parameter = Field(..., description='Параметры расчёта')
    formation_model: FormationModel | None = Field(None, description='Модель пласта')


class Segment(BaseModel):
    """Результирующий сегмент."""

    name: str = Field(..., description='Имя сегмента')
    group: str = Field(..., description='Группа сегментов')
    type: str = Field(..., description='Тип сегмента')
    value: PolygonValue = Field(..., description='Файл сегмента')
    polygon_id: str = Field(..., description='ID полигона, из которого создан сегмент')


class FormationResult(BaseModel):
    """Результат по пласту."""

    segment: list[Segment] = Field(..., description='Группы сегментов')
    name: str = Field(..., description='Имя пласта')


class CalculationResult(BaseCalculationResult):
    """Результат расчёта сегментов."""

    formation: FormationResult | None = Field(None, description='Данные созданных сегментов')
