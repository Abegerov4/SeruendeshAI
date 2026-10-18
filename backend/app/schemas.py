"""Pydantic-схемы строго по контракту из team/README.md §3.3."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr

Mode = Literal["walk", "car", "transit"]
Lang = Literal["ru", "kk", "en"]


# Strict-типы: "51.1" (строка) или true вместо числа — это ошибка клиента (422), а не повод угадывать.
Coord = StrictFloat | StrictInt


class Location(BaseModel):
    lat: Coord = Field(ge=-90, le=90)
    lon: Coord = Field(ge=-180, le=180)


class Profile(BaseModel):
    with_kids: StrictBool = False
    tourist: StrictBool = False
    accessibility: StrictBool = False
    group_size: StrictInt = Field(default=1, ge=1, le=50)


QUERY_MAX_CHARS = 1000  # столько текста реально уходит в разбор; длиннее — обрезаем, а не отказываем


class RecommendRequest(BaseModel):
    # Пустая строка допустима: ответим просьбой уточнить (200), а не 422.
    # Верхний предел — защита от злоупотреблений, а не «придуманный лимит» для обычных длинных сообщений.
    query: StrictStr = Field(max_length=20_000)
    location: Location | None = None
    time_budget_min: StrictInt | None = Field(default=None, ge=10, le=720)
    mode: Mode | None = None
    profile: Profile | None = None
    lang: Lang | None = None
    now: datetime | None = None


class UsedContext(BaseModel):
    location_source: Literal["gps_rounded", "landmark", "none"]
    location_label: str | None
    radius_m: int | None
    time_budget_min: int
    mode: Mode
    filters: list[str]
    now: datetime


class Recommendation(BaseModel):
    poi_id: str
    name: str
    category: str
    lat: float
    lon: float
    distance_m: int | None
    travel_min: int | None
    why: str
    visit_min: list[int] = Field(min_length=2, max_length=2)
    what_to_do: str
    open_status: Literal["open", "closed", "unknown"]
    open_confidence: Literal["high", "low", "none"]
    source: Literal["poi_data", "generated"]
    source_url: str | None
    rating: float | None


class Route(BaseModel):
    order: list[str]
    total_min: int


class RecommendResponse(BaseModel):
    request_id: str
    used_context: UsedContext
    recommendations: list[Recommendation]
    route: Route | None
    notes: list[str]
    disclaimer: str


class PoiBrief(BaseModel):
    id: str
    name: str
    category: str
    lat: float
    lon: float
