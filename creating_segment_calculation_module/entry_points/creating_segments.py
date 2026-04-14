"""Точка входа расчетного модуля.

Содержит вызов расчета, функцию calculate.
Содержит импортированные модели входных и выходных данных, CalculationInput, CalculationResult
"""

from creating_segment_calculation_module.creating_segments import creating_segments
from creating_segment_calculation_module.models.creating_segments import CalculationInput
from creating_segment_calculation_module.models.creating_segments import CalculationResult


def calculate(input_data: CalculationInput, /, **kwargs) -> CalculationResult:
    """Модуль для создания сегментов.

    На входе полигон с множеством линий и опционально скважины с контуром модели.
    На выходе Сегменты для каждой полилинии.
    """
    storage = kwargs['storage']

    return creating_segments(input_data, storage)
