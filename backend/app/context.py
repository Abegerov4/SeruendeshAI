"""Real-time context: local time, KZ public holidays, daylight and weather (Open-Meteo, no key)."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import holidays
import httpx
from astral import LocationInfo
from astral.sun import sun

from app.i18n import t

log = logging.getLogger("app.context")
TZ = ZoneInfo("Asia/Almaty")  # Astana is UTC+5 since 2024-03-01 (tzdata >= 2024a)
CITY = LocationInfo("Astana", "KZ", "Asia/Almaty", 51.1605, 71.4460)
_KZ = holidays.country_holidays("KZ", language="en_US", observed=True)
_KZ_KK = holidays.country_holidays("KZ", language="kk", observed=True)
_RU = {"New Year's Day": "Новый год", "Orthodox Christmas": "Рождество", "International Women's Day": "8 Марта",
       "Nowruz Holiday": "Наурыз", "Kazakhstan's People Solidarity Holiday": "День единства народа Казахстана",
       "Defender of the Fatherland Day": "День защитника Отечества", "Victory Day": "День Победы",
       "Eid al-Adha": "Курбан айт", "Capital Day": "День столицы", "Constitution Day": "День Конституции",
       "Republic Day": "День Республики", "Independence Day": "День Независимости"}


def holiday_name(day: dt.date, en: str | None, lang: str) -> str | None:
    """The holiday in the answer's language («День Республики», not «Republic Day»)."""
    if not en or lang == "en":
        return en
    if lang == "kk":
        return _KZ_KK.get(day) or en
    base = en.replace(" (observed)", "").replace(" (estimated)", "")
    ru = _RU.get(base, en)
    return ru + (" (перенос)" if "(observed)" in en else "")
_wx_cache: dict[str, tuple[float, dict | None]] = {}


@dataclass
class Context:
    now: dt.datetime  # tz-aware local
    holiday: str | None
    is_dark: bool
    sunset: dt.datetime
    weather: dict | None
    max_outdoor_min: int
    winter: bool

    @property
    def local_naive(self) -> dt.datetime:
        return self.now.replace(tzinfo=None)

    @property
    def snowing(self) -> bool:
        return bool(self.weather and (self.weather.get("snowfall") or 0) > 0)


def parse_now(override: str | None) -> dt.datetime:
    if override:
        try:
            d = dt.datetime.fromisoformat(override.replace("Z", "+00:00"))
            return d.astimezone(TZ) if d.tzinfo else d.replace(tzinfo=TZ)
        except ValueError:
            pass
    return dt.datetime.now(TZ)


async def fetch_weather(client: httpx.AsyncClient) -> dict | None:
    key = "astana"
    hit = _wx_cache.get(key)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    wx, air = await asyncio.gather(
        client.get("https://api.open-meteo.com/v1/forecast", timeout=2.5, params={
            "latitude": CITY.latitude, "longitude": CITY.longitude, "timezone": "Asia/Almaty", "wind_speed_unit": "ms",
            "current": "temperature_2m,apparent_temperature,precipitation,snowfall,weather_code,wind_speed_10m,wind_gusts_10m,is_day"}),
        # winter smog from coal heating is a real Astana factor: CAMS air quality from the same provider
        client.get("https://air-quality-api.open-meteo.com/v1/air-quality", timeout=2.5, params={
            "latitude": CITY.latitude, "longitude": CITY.longitude, "timezone": "Asia/Almaty", "current": "us_aqi,pm2_5"}),
        return_exceptions=True)
    try:
        wx.raise_for_status()
        cur = wx.json()["current"]
    except Exception as e:  # never invent weather: return None and say "unknown"
        log.warning("weather unavailable: %s", type(e).__name__)
        cur = None
    try:
        air.raise_for_status()
        aq = air.json()["current"]
        if cur is not None and aq.get("us_aqi") is not None:
            cur = {**cur, "us_aqi": aq["us_aqi"], "pm2_5": aq.get("pm2_5")}
    except Exception as e:  # air quality is optional context
        log.info("air quality unavailable: %s", type(e).__name__)
    _wx_cache[key] = (time.time(), cur)
    return cur


def max_outdoor_minutes(w: dict | None, with_child: bool) -> int:
    """Comfortable continuous minutes outdoors from feels-like temperature and gusts."""
    if not w:
        return 60
    feels = w.get("apparent_temperature")
    gust = w.get("wind_gusts_10m") or 0
    if feels is None:
        return 60
    if with_child:
        feels -= 5  # one step stricter with children
    aqi = w.get("us_aqi") or 0
    if aqi >= 151 or (with_child and aqi >= 101):
        return 20 if feels > -20 else 10  # polluted air: short outdoor legs, indoor places first
    if feels <= -30 or gust >= 20:
        return 0
    if feels <= -20:
        return 10
    if feels <= -10 or (w.get("precipitation") or 0) > 0.3 or gust >= 15:
        return 20
    if feels >= 32:
        return 25
    return 60


def build_context(now: dt.datetime, weather: dict | None, with_child: bool) -> Context:
    s = sun(CITY.observer, date=now.date(), tzinfo=TZ)
    dark = not (s["sunrise"] <= now <= s["sunset"])
    return Context(now=now, holiday=_KZ.get(now.date()), is_dark=dark, sunset=s["sunset"], weather=weather,
                   max_outdoor_min=max_outdoor_minutes(weather, with_child), winter=now.month in (11, 12, 1, 2, 3))


def weather_out(ctx: Context, lang: str) -> dict | None:
    w = ctx.weather
    if not w:
        return None
    desc = t("wx", lang, t=round(w["temperature_2m"]), f=round(w["apparent_temperature"]), w=round(w["wind_speed_10m"]))
    precip = (w.get("precipitation") or 0) > 0 or (w.get("snowfall") or 0) > 0
    if precip:
        desc += t("wx_precip", lang)
    return {"temperature_c": w.get("temperature_2m"), "feels_like_c": w.get("apparent_temperature"),
            "wind_ms": w.get("wind_speed_10m"), "precipitation": precip, "description": desc,
            "max_outdoor_min": ctx.max_outdoor_min,
            "us_aqi": w.get("us_aqi"), "pm2_5": w.get("pm2_5"),
            "source": "demo override" if w.get("override") else "Open-Meteo.com (CC BY 4.0)"}
