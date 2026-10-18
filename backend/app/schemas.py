"""Pydantic-схемы строго по контракту из team/README.md §3.3."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Mode = Literal["walk", "car", "transit"]
Lang = Literal["ru", "kk", "en"]


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Profile(BaseModel):
    with_kids: bool = False
    tourist: bool = False
    accessibility: bool = False
    group_size: int = Field(default=1, ge=1, le=50)


class RecommendRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    location: Location | None = None
    time_budget_min: int | None = Field(default=None, ge=10, le=720)
    mode: Mode | None = None
    profile: Profile | None = None
    lang: Lang | None = None
    now: datetime | None = None

    @field_validator("query")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query is empty")
        return v


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
