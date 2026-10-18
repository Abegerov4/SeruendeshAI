"""Генерация рекомендаций: LLM выбирает 1–3 места из кандидатов и объясняет «почему».

Всё фактическое (расстояние, время в пути, часы, рейтинг, ссылка) потом подставляет код, а не LLM.
Если LLM недоступна или ответ невалиден — шаблонный fallback по топ-кандидатам.
"""
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from . import llm
from .guards import clean_llm_text, wrap_untrusted
from .intent import Intent
from .routing import default_visit

PROMPT = (Path(__file__).parent / "prompts" / "generate.md").read_text(encoding="utf-8")
LANG_NAME = {"ru": "русский", "kk": "казахский", "en": "английский"}
# такие заметки система добавляет сама — дубли от LLM выкидываем
DUP_NOTE = re.compile(r"час(ы|ов) работы|режим работы|opening hours|маршрут|route|обратн|return", re.IGNORECASE)


class LlmRec(BaseModel):
    poi_id: str
    why: str
    visit_min: list[int] = Field(min_length=2, max_length=2)
    what_to_do: str
    source: str = "poi_data"


class LlmAnswer(BaseModel):
    recommendations: list[LlmRec]
    notes: list[str] = Field(default_factory=list)


def human_tags(poi: dict) -> list[str]:
    """Без служебных OSM-тегов вида amenity=cafe / wikipedia=kk:… — они шумят в промпте."""
    return [t for t in poi.get("tags", []) if "=" not in t]


def _candidate_view(c: dict) -> dict:
    return {
        "poi_id": c["id"], "name": c["name"], "category": c["category"], "tags": human_tags(c),
        "description": (c.get("description") or "")[:400], "distance_m": c.get("distance_m"),
        "travel_min": c.get("travel_min"), "open_status": c["open_status"], "rating": c.get("rating"),
        "kid_friendly": c.get("kid_friendly"), "wheelchair": c.get("wheelchair"),
    }


def _user_block(query: str, intent: Intent, location_label: str | None) -> str:
    return json.dumps({
        "query": query,
        "location": location_label or "не указана",
        "time_budget_min": intent.time_budget_min,
        "mode": intent.mode,
        "constraints": intent.constraints.model_dump(),
        "group_size": intent.group_size,
    }, ensure_ascii=False)


def llm_generate(query: str, intent: Intent, candidates: list[dict], location_label: str | None) -> tuple[list[dict], list[str]] | None:
    system = PROMPT.replace("{lang}", LANG_NAME.get(intent.lang, "русский"))
    user = (
        f"Запрос пользователя:\n<user_query>\n{_user_block(query, intent, location_label)}\n</user_query>\n\n"
        f"Кандидаты:\n{wrap_untrusted([_candidate_view(c) for c in candidates])}"
    )
    for _ in range(2):  # один ретрай при невалидном ответе
        data = llm.chat_json(system, user, role="decision", name="decide-recommendations")
        if not data:
            return None
        try:
            ans = LlmAnswer.model_validate(data)
        except ValidationError:
            continue
        valid_ids = {c["id"] for c in candidates}
        recs, seen = [], set()
        for r in ans.recommendations:
            if r.poi_id not in valid_ids or r.poi_id in seen:  # защита от галлюцинаций
                continue
            seen.add(r.poi_id)
            lo, hi = sorted(max(5, min(v, 600)) for v in r.visit_min)
            recs.append({
                "poi_id": r.poi_id,
                "why": clean_llm_text(r.why),
                "visit_min": [lo, hi],
                "what_to_do": clean_llm_text(r.what_to_do),
                "source": "generated" if r.source == "generated" else "poi_data",
            })
        notes = [clean_llm_text(n, 200) for n in ans.notes if n.strip() and not DUP_NOTE.search(n)]
        if recs:
            return recs[:3], notes[:1]
        if not ans.recommendations:
            # модель осознанно решила, что ничего не подходит — это ответ, а не сбой: шаблон не подставляем
            return [], notes[:1]
        # все poi_id невалидны (галлюцинация) — ретрай
    return None


# ---------- шаблонный fallback ----------
CATEGORY_LABEL = {
    "ru": {"cafe": "Кафе", "restaurant": "Ресторан", "bar": "Бар", "nightlife": "Ночное место", "museum": "Музей",
           "gallery": "Галерея", "theatre": "Театр", "cinema": "Кинотеатр", "park": "Парк", "viewpoint": "Смотровая",
           "monument": "Памятник", "attraction": "Достопримечательность", "playground": "Детская площадка",
           "mall": "Торговый центр", "library": "Библиотека", "coworking": "Коворкинг", "sport": "Спорт", "other": "Место"},
    "en": {"cafe": "Cafe", "restaurant": "Restaurant", "bar": "Bar", "nightlife": "Nightlife", "museum": "Museum",
           "gallery": "Gallery", "theatre": "Theatre", "cinema": "Cinema", "park": "Park", "viewpoint": "Viewpoint",
           "monument": "Monument", "attraction": "Attraction", "playground": "Playground", "mall": "Mall",
           "library": "Library", "coworking": "Coworking", "sport": "Sport", "other": "Place"},
}
WHAT_TO_DO = {
    "ru": {"cafe": "Взять кофе и сесть в тихом углу", "restaurant": "Поужинать без спешки",
           "park": "Пройти круг по главной аллее", "viewpoint": "Подняться наверх и сделать панорамные фото",
           "museum": "Начать с главного зала и интерактивных экспозиций", "gallery": "Посмотреть текущую экспозицию",
           "playground": "Дать ребёнку поиграть, рядом есть где присесть", "mall": "Зайти в фуд-корт и развлекательную зону",
           "attraction": "Осмотреть снаружи и сделать фото", "monument": "Осмотреть и сделать фото",
           "bar": "Послушать музыку и отдохнуть", "nightlife": "Провести вечер с компанией",
           "coworking": "Поработать в тихой зоне", "library": "Посидеть в читальном зале"},
    "en": {"cafe": "Grab a coffee and find a quiet corner", "restaurant": "Have an unhurried meal",
           "park": "Walk a loop along the main alley", "viewpoint": "Go up and take panoramic photos",
           "museum": "Start with the main hall and interactive exhibits", "gallery": "See the current exhibition",
           "playground": "Let the kids play, there are benches nearby", "mall": "Visit the food court and entertainment area",
           "attraction": "Look around and take photos", "monument": "Look around and take photos",
           "bar": "Enjoy the music and relax", "nightlife": "Spend the evening with friends",
           "coworking": "Work in the quiet zone", "library": "Sit in the reading room"},
}


def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]


def template_generate(intent: Intent, candidates: list[dict]) -> list[dict]:
    lang = "en" if intent.lang == "en" else "ru"
    recs = []
    for c in candidates[:3]:
        label = CATEGORY_LABEL[lang].get(c["category"], CATEGORY_LABEL[lang]["other"])
        dist = c.get("distance_m")
        if lang == "en":
            near = f"{dist} m away" if dist is not None else "in the city"
        else:
            near = f"в {dist} м от вас" if dist is not None else "в городе"
        desc = _first_sentence(c.get("description"))
        why = f"{label} {near}. {desc}".strip()
        recs.append({
            "poi_id": c["id"],
            "why": clean_llm_text(why),
            "visit_min": default_visit(c["category"], intent.time_budget_min),
            "what_to_do": WHAT_TO_DO[lang].get(c["category"], WHAT_TO_DO[lang]["attraction"]),
            "source": "poi_data" if desc and c.get("description_source") != "llm_generated" else "generated",
        })
    return recs
