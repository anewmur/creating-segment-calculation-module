from pathlib import Path

from nedra_calculate_ontology.ontology_model import File

from .exceptions import ContourFileFormatError
from .exceptions import ContourFileNotFoundError
from .models.contour import Contour


def load_contour(contour_file: File, contour_name: str) -> Contour:
    path = Path(contour_file.path)

    try:
        return Contour.model_validate_json(
            path.read_text(encoding='utf-8')
        )
    except FileNotFoundError:
        raise ContourFileNotFoundError(contour_name)
    except Exception as exc:
        raise ContourFileFormatError(str(exc))


def load_contour_from_external_format(
    contour_file: File,
    contour_name: str,
) -> Contour:
    return load_contour(contour_file, contour_name)