from pathlib import Path
from pydantic import BaseModel, Field


class Storage:
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def get_temp_dir(self) -> Path:
        return self._base_dir



class File(BaseModel):
    path: str = Field(..., description="Путь к файлу")