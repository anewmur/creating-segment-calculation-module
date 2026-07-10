from pydantic import BaseModel
from pydantic import Field


class Point(BaseModel):
    x: float
    y: float
    z: float = 0.0


class Line(BaseModel):
    points: list[Point] = Field(default_factory=list)


class Contour(BaseModel):
    lines: list[Line] = Field(default_factory=list)