from pydantic import BaseModel
from pydantic import Field


class Messages(BaseModel):
    """Схема сообщений о результатах расчёта."""

    info: list[str] = Field(
        default_factory=list,
        description='Информационные сообщения о процессе расчёта',
    )
    warning: list[str] = Field(
        default_factory=list,
        description='Предупреждающие сообщения о нестандартных ситуациях',
    )
    error: list[str] = Field(
        default_factory=list,
        description='Сообщения об ошибках, прервавших расчёт',
    )


class BaseCalculationResult(BaseModel):
    """Схема результата."""

    messages: Messages = Field(default_factory=Messages)