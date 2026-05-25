from pydantic import BaseModel, Field


class File(BaseModel):
    path: str = Field(..., description="Путь к файлу")
