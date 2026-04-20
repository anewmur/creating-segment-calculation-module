from enum import Enum
from dataclasses import dataclass

class OverlapCase(Enum):
    all_points_inside_one_polygon = "all_points_inside_one_polygon"
    candidate_block_4 = "candidate_block_4"
    candidate_block_5 = "candidate_block_5"
    unsupported = "unsupported"

class ContainmentHandlingStatus(Enum):
    """Результат обработки пары полигонов как потенциальной вложенности."""

    not_containment = 'not_containment'
    rebuilt = 'rebuilt'
    exclude_outer = 'exclude_outer'


@dataclass(frozen=True, slots=True)
class ContainmentHandlingResult:
    """Явный результат обработки пары полигонов в режиме вложенности."""

    status: ContainmentHandlingStatus
    outer_index: int | None = None


class TwoPointsRebuildStatus(Enum):
    """Результат обработки пары полигонов в ветке с двумя точками пересечения."""
    rebuilt = 'rebuilt'
    rebuild_failed = 'rebuild_failed'



class OverlapCase(Enum):
    all_points_inside_one_polygon = "all_points_inside_one_polygon"
    candidate_block_4 = "candidate_block_4"
    candidate_block_5 = "candidate_block_5"
    unsupported = "unsupported"

class ManyPointsRebuildStatus(Enum):
    """Результат обработки пары полигонов в ветке со сложным пересечением."""

    rebuilt = 'rebuilt'
    rebuild_failed = 'rebuild_failed'


