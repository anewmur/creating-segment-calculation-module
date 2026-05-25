"""Точка входа расчетного модуля.

Содержит вызов расчета, функцию calculate.
Содержит импортированные модели входных и выходных данных, CalculationInput, CalculationResult
"""

from creating_segment_calculation_module.creating_segment import creating_segment
from creating_segment_calculation_module.models.creating_segment import CalculationInput
from creating_segment_calculation_module.models.creating_segment import CalculationResult


def calculate(input_data: CalculationInput, /, **kwargs) -> CalculationResult:
    """Модуль для создания сегментов.

    На входе список полигонов и параметры.
    На выходе Сегменты.
    """
    storage = kwargs['storage']

    return creating_segment(input_data, storage)
