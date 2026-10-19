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
    candidate_ids = {c["id"] for c in candidates}
    def accepted_output(data):
        answer = LlmAnswer.model_validate(data)
        return not answer.recommendations or any(r.poi_id in candidate_ids for r in answer.recommendations)
    for _ in range(2):  # один ретрай при невалидном ответе
        data = llm.chat_json(system, user, role="decision", name="decide-recommendations",
                             validate_output=accepted_output)
        if not data:
            return None
        try:
            ans = LlmAnswer.model_validate(data)
        except ValidationError:
            continue
        by_id = {c["id"]: c for c in candidates}
        valid_ids = set(by_id)
        recs, seen = [], set()
        for r in ans.recommendations:
            if r.poi_id not in valid_ids or r.poi_id in seen:  # защита от галлюцинаций
                continue
            seen.add(r.poi_id)
            lo, hi = sorted(max(5, min(v, 600)) for v in r.visit_min)
            why, what, grounded = template_texts(by_id[r.poi_id], _lang(intent))
            source = "poi_data" if grounded else "generated"
            recs.append({"poi_id": r.poi_id, "why": why, "visit_min": [lo, hi], "what_to_do": what, "source": source})
        # Free model notes can assert the same unsupported facts as card prose.
        notes = []
        if recs:
            return recs[:3], notes[:1]
        if not ans.recommendations:
            # модель осознанно решила, что ничего не подходит — это ответ, а не сбой: шаблон не подставляем
            note = {"ru": "Для текущего запроса подбор не сформирован; попробуйте изменить фильтры или локацию.",
                    "kk": "Бұл сұрауға орындар таңдалмады; сүзгілерді немесе орынды өзгертіп көріңіз.",
                    "en": "No selection was made for this request; try changing filters or location."}[_lang(intent)]
            return [], [note]
        # все poi_id невалидны (галлюцинация) — ретрай
    return None


# ---------- шаблонный fallback ----------
CATEGORY_LABEL = {
    "ru": {"cafe": "Кафе", "restaurant": "Ресторан", "bar": "Бар", "nightlife": "Ночное место", "museum": "Музей",
           "gallery": "Галерея", "theatre": "Театр", "cinema": "Кинотеатр", "park": "Парк", "viewpoint": "Смотровая",
           "monument": "Памятник", "attraction": "Достопримечательность", "playground": "Детская площадка",
           "mall": "Торговый центр", "library": "Библиотека", "coworking": "Коворкинг", "sport": "Спорт", "other": "Место"},
    "kk": {"cafe": "Кафе", "restaurant": "Мейрамхана", "bar": "Бар", "nightlife": "Түнгі орын", "museum": "Мұражай",
           "gallery": "Галерея", "theatre": "Театр", "cinema": "Кинотеатр", "park": "Саябақ", "viewpoint": "Көру алаңы",
           "monument": "Ескерткіш", "attraction": "Көрікті орын", "playground": "Балалар алаңы",
           "mall": "Сауда орталығы", "library": "Кітапхана", "coworking": "Коворкинг", "sport": "Спорт", "other": "Орын"},
    "en": {"cafe": "Cafe", "restaurant": "Restaurant", "bar": "Bar", "nightlife": "Nightlife", "museum": "Museum",
           "gallery": "Gallery", "theatre": "Theatre", "cinema": "Cinema", "park": "Park", "viewpoint": "Viewpoint",
           "monument": "Monument", "attraction": "Attraction", "playground": "Playground", "mall": "Mall",
           "library": "Library", "coworking": "Coworking", "sport": "Sport", "other": "Place"},
}
# Нейтральные действия: без утверждений, которых нет в данных (тишина, розетки, «интерактив» и т.п.)
WHAT_TO_DO = {
    "ru": {"cafe": "Зайти на кофе или перекус", "restaurant": "Пообедать или поужинать",
           "park": "Пройтись по парку", "viewpoint": "Посмотреть на город и сделать фото",
           "museum": "Посмотреть экспозицию", "gallery": "Посмотреть экспозицию",
           "playground": "Дать ребёнку поиграть", "mall": "Прогуляться по торговому центру",
           "attraction": "Осмотреть место и сделать фото", "monument": "Осмотреть и сделать фото",
           "bar": "Посидеть вечером", "nightlife": "Провести вечер", "theatre": "Уточнить афишу и сходить на спектакль",
           "cinema": "Уточнить расписание сеансов", "coworking": "Поработать", "library": "Почитать",
           "sport": "Позаниматься или посмотреть", "other": "Заглянуть по пути"},
    "kk": {"cafe": "Кофе ішуге немесе тамақтануға бару", "restaurant": "Түскі не кешкі ас ішу",
           "park": "Саябақта серуендеу", "viewpoint": "Қалаға қарап, суретке түсіру",
           "museum": "Экспозицияны көру", "gallery": "Экспозицияны көру",
           "playground": "Балаға ойнауға мүмкіндік беру", "mall": "Сауда орталығын аралау",
           "attraction": "Орынды аралап, суретке түсіру", "monument": "Көріп, суретке түсіру",
           "bar": "Кешті өткізу", "nightlife": "Кешті өткізу", "theatre": "Афишаны тексеріп, қойылымға бару",
           "cinema": "Сеанс кестесін тексеру", "coworking": "Жұмыс істеу", "library": "Кітап оқу",
           "sport": "Жаттығу немесе көру", "other": "Жол бойы кіру"},
    "en": {"cafe": "Stop by for a coffee or a snack", "restaurant": "Have lunch or dinner",
           "park": "Take a walk in the park", "viewpoint": "Look at the city and take photos",
           "museum": "See the exhibition", "gallery": "See the exhibition",
           "playground": "Let the kids play", "mall": "Walk around the mall",
           "attraction": "Look around and take photos", "monument": "Look around and take photos",
           "bar": "Spend the evening", "nightlife": "Spend the evening", "theatre": "Check the schedule and see a show",
           "cinema": "Check the showtimes", "coworking": "Get some work done", "library": "Read for a while",
           "sport": "Work out or watch", "other": "Drop by on the way"},
}
NEAR = {"ru": ("в {d} м от вас", "в городе"), "kk": ("сізден {d} м жерде", "қалада"), "en": ("{d} m away", "in the city")}


def _lang(intent: Intent) -> str:
    return intent.lang if intent.lang in CATEGORY_LABEL else "ru"


def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]


def template_texts(c: dict, lang: str) -> tuple[str, str, bool]:
    """(why, what_to_do, grounded) по фактам POI — используется и как fallback, и для пустых ответов LLM."""
    label = CATEGORY_LABEL[lang].get(c["category"], CATEGORY_LABEL[lang]["other"])
    dist = c.get("distance_m")
    near = NEAR[lang][0].format(d=dist) if dist is not None else NEAR[lang][1]
    # Category and computed proximity are accepted fields. Source narrative can
    # contain unverified facility claims or injected instructions; it is not a
    # substitute for field-level evidence in this factual explanation.
    why = clean_llm_text(f"{label} {near}.")
    what = WHAT_TO_DO[lang].get(c["category"], WHAT_TO_DO[lang]["other"])
    return why, what, True


def template_generate(intent: Intent, candidates: list[dict]) -> list[dict]:
    lang = _lang(intent)
    # сначала места нужных категорий (запрос «прогулка» → парки, а не кафе); остальные — только если подходящих нет
    wanted = set(intent.categories)
    matching = [c for c in candidates if c["category"] in wanted]
    pool = matching or candidates
    recs = []
    for c in pool[:3]:
        why, what, grounded = template_texts(c, lang)
        recs.append({
            "poi_id": c["id"],
            "why": why,
            "visit_min": default_visit(c["category"], intent.time_budget_min),
            "what_to_do": what,
            # «что делать» — общая идея по категории, а не факт о месте; poi_data только если «почему» опирается на описание
            "source": "poi_data" if grounded else "generated",
        })
    return recs
