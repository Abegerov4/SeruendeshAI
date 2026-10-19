"""HTTP API contract (single source of truth; exported to docs/api/openapi.json)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

API_VERSION = "1.0"

Lang = Literal["ru", "kk", "en"]
TravelMode = Literal["walk", "car", "transit"]
ContractCategory = Literal["cafe", "restaurant", "bar", "nightlife", "museum", "gallery", "theatre", "cinema", "park",
                           "viewpoint", "monument", "attraction", "playground", "mall", "library", "coworking", "sport", "other"]
OpenStatus = Literal["open", "closing_soon", "closed", "always", "unknown"]
Confidence = Literal["high", "medium", "low"]


class _Out(BaseModel):
    # every field is present in responses (even when null) -> non-optional TS types
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class LatLon(BaseModel):
    model_config = ConfigDict(strict=True)
    lat: float = Field(ge=-90, le=90, description="Latitude; the client should round to 3 decimals (~100 m)")
    lon: float = Field(ge=-180, le=180, description="Longitude; the client should round to 3 decimals")


class WeatherOverride(BaseModel):
    """Test override of live weather (reproducible evaluations)."""
    model_config = ConfigDict(strict=True)
    temperature_c: float = Field(ge=-60, le=60)
    feels_like_c: float = Field(ge=-70, le=60)
    wind_ms: float = Field(0, ge=0, le=60)
    precipitation: bool = False


class Profile(BaseModel):
    model_config = ConfigDict(strict=True)
    with_kids: bool = False
    tourist: bool = False
    accessibility: bool = False
    group_size: int = Field(1, ge=1, le=50)


class RecommendRequest(BaseModel):
    model_config = ConfigDict(strict=True)  # "51.1" / "true" strings are rejected (422), like the team contract tests expect
    query: str = Field(description="Free text in RU/KK/EN, e.g. «Я возле Байтерека, хочу погулять час» (long text is truncated)")

    @field_validator("query", mode="before")
    @classmethod
    def _truncate(cls, v):
        return v[:1000] if isinstance(v, str) else v
    lang: Lang | None = Field(None, description="UI language; null = detect from the query")
    location: LatLon | None = Field(None, description="Approximate user position (rounded). Server rounds again.")
    landmark: str | None = Field(None, max_length=80, description="Landmark key or name from GET /api/meta instead of GPS")
    time_budget_min: int | None = Field(None, ge=10, le=480, description="Total time the user has (null = from text or 60)")
    mode: TravelMode | None = Field(None, description="Team contract §3.3: walk | car | transit")
    profile: Profile | None = Field(None, description="Team contract §3.3 profile (with_kids, tourist, accessibility, group_size)")
    travel_mode: TravelMode | None = Field(None, description="Alias of `mode`")
    with_child: bool | None = Field(None, description="Overrides profile.with_kids; null = detect from text")
    tourist: bool | None = None
    accessibility: bool | None = Field(None, description="Need step-free / wheelchair-accessible places")
    group_size: int | None = Field(None, ge=1, le=20)
    want_route: bool | None = Field(None, description="Ask for a 2–3 stop mini-route (default: auto)")
    now: str | None = Field(None, description="ISO datetime override for tests, e.g. 2026-10-18T19:30:00+05:00")
    weather: WeatherOverride | None = Field(None, description="Weather override for tests (null = live Open-Meteo)")
    refine: list[Literal["closer", "no_coffee", "indoor"]] = Field(
        default_factory=list, description="Follow-up refinements of the previous request: closer, no_coffee, indoor")


class Opening(_Out):
    status: OpenStatus
    confidence: Confidence
    label: str = Field(description="Human text in the response language, e.g. «Открыто до 22:00 (данные OSM)»")
    raw: str | None = Field(description="Original OSM opening_hours string, if any")
    next_change: str | None = Field(description="Local HH:MM of the next open/close change, if known")


class EventInfo(_Out):
    title: str
    starts_at: str | None
    url: str | None
    source: str
    price_from: str | None


class Recommendation(_Out):
    # --- team contract §3.3 fields
    poi_id: str = Field(description="POI id (osm:w123 / wd:Q123 / ov:...) or idea-N for AI ideas")
    name: str
    category: ContractCategory = Field(description="Contract category enum (team README §3.1)")
    lat: float
    lon: float
    distance_m: int = Field(description="Straight-line (haversine) distance from the start, metres")
    travel_min: int = Field(description="Travel minutes along the real street network (walk) or road estimate (car)")
    why: str = Field(description="Short motivation, 1–2 sentences")
    visit_min: tuple[int, int] = Field(description="[min, max] minutes on site")
    what_to_do: str = Field(description="Concrete action / plan on site")
    open_status: Literal["open", "closed", "unknown"]
    open_confidence: Literal["high", "low", "none"]
    source: Literal["poi_data", "generated"] = Field(description="poi_data = collected dataset; generated = AI idea")
    source_url: str | None = Field(description="Exactly the dataset source (OSM / Wikidata / Wikipedia page) or null")
    rating: float | None = Field(description="Always null in v1: no open rating source exists for Astana")
    website: str | None = Field(description="The place's own website, if known")
    # --- extensions (superset of the contract)
    rank: int
    category_detail: str = Field(description="Fine-grained category key (33 types), see GET /api/meta")
    category_label: str
    icon: str
    walk_distance_m: int | None = Field(description="Network walking distance (car: estimated road distance)")
    travel_mode: TravelMode
    visit_suggested_min: int
    leave_by: str | None = Field(description="HH:MM to leave this place to keep the user's deadline (flight etc.)")
    opening: Opening
    source_label: str
    data_sources: list[str] = Field(description="Where the facts come from: osm, wikidata, wikipedia, overture, ticketon, sxodim")
    popularity: float | None = Field(description="0..1 proxy from Wikipedia/Wikidata signals and data richness")
    features: list[str] = Field(description="Confirmed amenities in the response language (Wi-Fi, terrace, ...)")
    accessibility: Literal["yes", "limited", "no", "unknown"]
    badges: list[str] = Field(description="indoor, outdoor, kids, hidden_gem, event, popular, night, free")
    event: EventInfo | None
    address: str | None
    description: str | None = Field(description="Short description (Wikipedia extract or facts from tags)")
    description_source: str | None = Field(description="wikipedia | osm | template | generated")


class RouteLeg(_Out):
    from_id: str = Field(description="'start' or an item id")
    to_id: str
    distance_m: int
    travel_min: int
    polyline: list[tuple[float, float]] = Field(description="[[lat, lon], ...] for Leaflet")
    geometry: Literal["network", "straight"]


class Route(_Out):
    order: list[str] = Field(description="poi_ids in visiting order (team contract)")
    legs: list[RouteLeg]
    total_min: int = Field(description="Travel + visits (+ return leg if returns_to_start)")
    fits_budget: bool
    returns_to_start: bool
    summary: str


class WeatherInfo(_Out):
    temperature_c: float | None
    feels_like_c: float | None
    wind_ms: float | None
    precipitation: bool
    description: str
    max_outdoor_min: int = Field(description="Comfortable continuous minutes outdoors derived from feels-like/wind")
    source: str


class UsedLocation(_Out):
    source: Literal["gps_rounded", "landmark", "text_landmark", "none"]
    label: str
    lat: float
    lon: float
    precision_m: int


class Considered(_Out):
    name: str
    reason: str


class UsedContext(_Out):
    location_source: Literal["gps_rounded", "landmark", "none"]
    location_label: str | None
    radius_m: int | None
    time_budget_min: int
    mode: TravelMode
    filters: list[str]
    now: str = Field(description="ISO datetime used for opening hours (Astana, UTC+5)")
    location: UsedLocation | None
    local_time: str
    weekday: str
    is_holiday: str | None
    is_dark: bool
    weather: WeatherInfo | None
    speed_kmh: float
    party: str
    parsed_from_query: dict = Field(description="What the system understood from the text (categories, needs, deadline)")
    relaxations: list[str]
    funnel: dict[str, int] = Field(description="POIs total -> within reach -> after filters -> shown")
    data_sources: list[str]
    data_built_at: str | None
    privacy: str


class LLMUsage(_Out):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = Field(0.0, description="Estimated USD from the price table in config; null = unknown model price")


class LLMInfo(_Out):
    mode: Literal["llm", "template"]
    model: str | None
    latency_ms: int
    usage: LLMUsage = Field(default_factory=LLMUsage, description="Tokens and estimated cost of all LLM calls of this request")


class RecommendResponse(_Out):
    api_version: str = API_VERSION
    request_id: str
    lang: Lang
    summary: str
    recommendations: list[Recommendation] = Field(description="1–3 places from the dataset (source=poi_data)")
    ideas: list[Recommendation] = Field(description="AI-generated micro-activities (source=generated), anchored to a recommended place")
    route: Route | None
    used_context: UsedContext
    considered: list[Considered] = Field(description="A few places that were rejected and why (transparency)")
    notes: list[str]
    disclaimer: str
    ai_generated: bool = True
    llm: LLMInfo
    off_topic: bool = Field(False, description="The query is not about places/walks in Astana: no recommendations, see notes")


class PhotoGuess(_Out):
    recognized: bool = Field(description="True when a known place was identified confidently enough to search around it")
    place_id: str | None = Field(description="Landmark key (GET /api/meta) or POI id the photo shows")
    kind: Literal["landmark", "poi"] | None
    name: str | None
    confidence: Literal["low", "medium", "high"]
    description: str = Field(description="Short description of the photo by the AI")


class PhotoRecommendResponse(RecommendResponse):
    photo_guess: PhotoGuess


class LandmarkOut(_Out):
    key: str
    name: str
    lat: float
    lon: float


class CategoryOut(_Out):
    key: str
    group: str
    labels: dict[str, str]
    icon: str


class MetaFeatures(_Out):
    password_reset_email: bool = Field(False, description="SMTP is configured: password reset by email works")
    photo: bool = Field(False, description="LLM is configured: POST /api/recommend/photo works")
    mcp: bool = Field(True, description="MCP connector is served at /connector/mcp")


class MetaResponse(_Out):
    api_version: str = API_VERSION
    landmarks: list[LandmarkOut]
    categories: list[CategoryOut]
    data_built_at: str | None
    poi_count: int
    sources: dict[str, str]
    features: MetaFeatures = Field(default_factory=MetaFeatures)


class PoiBrief(_Out):
    id: str
    name: str
    category: ContractCategory
    category_detail: str
    lat: float
    lon: float


class HealthResponse(_Out):
    status: Literal["ok", "degraded"]
    pois: int = Field(description="Team contract field")
    llm: Literal["ok", "off"] = Field(description="Team contract field")
    poi_count: int
    events: int
    dense_retrieval: bool
    walk_graph: bool
    llm_configured: bool
    data_built_at: str | None


class FeedbackRequest(BaseModel):
    poi_id: str = Field(max_length=64)
    kind: Literal["closed", "wrong_hours", "not_as_described", "great", "other"]


class FeedbackResponse(_Out):
    ok: bool
    message: str
