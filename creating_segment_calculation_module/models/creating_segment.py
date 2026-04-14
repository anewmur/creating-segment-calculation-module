"""Модели для модуля."""

from enum import Enum

# from nedra_calculate_ontology.ontology_model import File
from tests.viz_test.utils import File



from pydantic import BaseModel


class SegmentType(Enum):
    """Типы сегментов."""

    # Ячейки Вороного
    voronoi_cell = 'Контур питания'
    #  Тектонический блок
    fault_block = 'Граница блока'
    #  Категория  запасов
    reserves_category = 'Граница категорий'
    #  Ячейки заводнения
    flood_cell = 'Ячейки'
    #  Общий
    general = 'Граница общая'


class PolygonValue(BaseModel):
    """Схема значения полигона."""

    file: File


class Polygon(BaseModel):
    """Схема Полигона."""

    name: str | None = None
    type: str | None = None
    value: PolygonValue


class Segment(BaseModel):
    """Схема сегмента, который такой же полигон."""

    name: str
    type: str
    value: PolygonValue


class SegmentParameters(BaseModel):
    """Схема параметров сегмента."""

    unite: bool
    segment_name: str
    segment_type: str
    border_model: PolygonValue


class Parameter(BaseModel):
    """Модель параметров."""

    segment: SegmentParameters


class CalculationInput(BaseModel):
    """Схема входных данных для модуля."""

    polygon: list[Polygon]
    parameter: Parameter


class CalculationResult(BaseModel):
    """Схема результата."""

    polygon: list[Segment]
