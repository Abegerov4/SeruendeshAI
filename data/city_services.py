"""Source-bound city activities, separate from point-of-interest geometry.

Collection time is not validity. Undated or yearless timetables remain facts and
cannot enter ``dated_departures``. A route's pass-by locations are not boarding
stops. Search aliases are editorial translations, not provider language claims.
"""
from datetime import date, time
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator


class ServiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Validity(ServiceModel):
    precision: Literal["undated", "exact", "seasonal", "year_unspecified"] = "undated"
    valid_from: date | None = None
    valid_to: date | None = None
    months: list[Annotated[int, Field(ge=1, le=12)]] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not follow valid_to")
        if self.precision == "year_unspecified" and (self.valid_from or self.valid_to):
            raise ValueError("year-unspecified evidence must not claim a dated interval")
        return self


class Evidence(ServiceModel):
    source_url: str = Field(pattern=r"^https?://[^\s]+$", min_length=10)
    checked_at: AwareDatetime
    excerpt: str = Field(min_length=1)
    validity: Validity = Field(default_factory=Validity)
    archive_path: str | None = None


EvidenceList = Annotated[list[Evidence], Field(min_length=1)]


class ServiceFact(ServiceModel):
    field: str = Field(min_length=1)
    value: str | StrictInt | StrictFloat | bool | list[str]
    unit: str | None = None
    status: Literal["confirmed", "conflicting"] = "confirmed"
    evidence: EvidenceList
    validity: Validity = Field(default_factory=Validity)
    notes: str | None = None


class Operator(ServiceModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    evidence: EvidenceList
    facts: list[ServiceFact] = Field(default_factory=list)


class ServiceStop(ServiceModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: Literal["boarding", "visit", "pass_by"]
    canonical_poi_id: str | None = None
    map_url: str | None = Field(default=None, pattern=r"^https?://[^\s]+$")
    evidence: EvidenceList
    notes: str | None = None


class ServiceRoute(ServiceModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    stops: list[ServiceStop] = Field(default_factory=list)
    evidence: EvidenceList


class TicketOffer(ServiceModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    amount: Annotated[StrictInt | StrictFloat, Field(ge=0)]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    unit: Literal["per_person", "per_group", "per_person_group_size"] = "per_person"
    group_size: int | None = Field(default=None, ge=1)
    age_min: int | None = Field(default=None, ge=0)
    age_max: int | None = Field(default=None, ge=0)
    age_max_inclusive: bool | None = None
    status: Literal["confirmed", "conflicting"] = "confirmed"
    evidence: EvidenceList
    validity: Validity = Field(default_factory=Validity)
    notes: str | None = None

    @model_validator(mode="after")
    def ordered_ages(self):
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("age_min must not exceed age_max")
        return self


class DatedDeparture(ServiceModel):
    date: date
    time: time
    timezone: Literal["Asia/Almaty"] = "Asia/Almaty"
    boarding_stop_id: str
    evidence: EvidenceList

    @model_validator(mode="after")
    def explicitly_dated(self):
        if self.time.tzinfo is not None:
            raise ValueError("departure time must be local to the declared timezone, without an offset")
        if not any(e.validity.precision == "exact" and e.validity.valid_from is not None
                   and e.validity.valid_to is not None
                   and e.validity.valid_from <= self.date <= e.validity.valid_to for e in self.evidence):
            raise ValueError("departure needs evidence explicitly valid on its full calendar date")
        return self


class CityService(ServiceModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: dict[Literal["ru", "kk", "en"], list[str]] = Field(default_factory=dict)
    kind: Literal["bus_tour", "walking_tour", "river_cruise", "guided_museum", "cultural_activity", "city_tour"]
    operator_id: str | None = None
    evidence: EvidenceList
    facts: list[ServiceFact] = Field(default_factory=list)
    routes: list[ServiceRoute] = Field(default_factory=list)
    ticket_offers: list[TicketOffer] = Field(default_factory=list)
    dated_departures: list[DatedDeparture] = Field(default_factory=list)
    booking_rules: list[ServiceFact] = Field(default_factory=list)
    schedule_status: Literal["dated", "date_unverified", "on_request", "not_published"] = "not_published"

    @model_validator(mode="after")
    def departure_stops_exist(self):
        if len({route.id for route in self.routes}) != len(self.routes):
            raise ValueError("duplicate route id within service")
        if len({offer.id for offer in self.ticket_offers}) != len(self.ticket_offers):
            raise ValueError("duplicate ticket id within service")
        stops = {stop.id for route in self.routes for stop in route.stops if stop.role == "boarding"}
        if any(departure.boarding_stop_id not in stops for departure in self.dated_departures):
            raise ValueError("dated departure must reference this service's verified boarding stop")
        return self


class CityServicesCatalog(ServiceModel):
    schema_version: Literal[1] = 1
    as_of: date
    collected_at: AwareDatetime
    operators: list[Operator] = Field(default_factory=list)
    services: list[CityService] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_references(self):
        operator_ids = {operator.id for operator in self.operators}
        service_ids = {service.id for service in self.services}
        if len(operator_ids) != len(self.operators) or len(service_ids) != len(self.services):
            raise ValueError("duplicate operator or service id")
        if any(service.operator_id is not None and service.operator_id not in operator_ids for service in self.services):
            raise ValueError("service operator is absent from catalog")
        return self


DEFAULT_CATALOG_PATH = Path(__file__).parent / "sources" / "city_services_2026-10-19.json"


def load_city_services(path: str | Path | None = None) -> CityServicesCatalog:
    """Load and validate a catalog; errors are explicit rather than an empty success."""
    return CityServicesCatalog.model_validate_json(Path(path or DEFAULT_CATALOG_PATH).read_text(encoding="utf-8"))


def departures_on(service: CityService, day: date) -> list[DatedDeparture]:
    """Return only explicitly dated departures for the requested calendar day."""
    return sorted((departure for departure in service.dated_departures if departure.date == day), key=lambda d: d.time)
