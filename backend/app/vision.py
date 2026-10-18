"""Мультимодальность: «сфоткай, что видишь» → узнаём место → рекомендации рядом.

Зачем: турист часто не знает названий и не хочет включать GPS. Фото ориентира заменяет геолокацию.
Приватность: фото пережимается в памяти, EXIF (в т.ч. GPS) удаляется до отправки в LLM, ничего не сохраняется.
Модель выбирает место только из закрытого списка известных ориентиров/POI — так она не выдумает несуществующее.
"""
import base64
import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from . import llm
from . import rag_adapter as rag

log = logging.getLogger("backend.vision")

PROMPT = (Path(__file__).parent / "prompts" / "photo_landmark.md").read_text(encoding="utf-8")
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1024

# Крупные ориентиры Астаны — узнаваемы на фото, даже если их нет в POI-базе
KNOWN_LANDMARKS = [
    "Байтерек", "Хан Шатыр", "Mega Silk Way", "EXPO / Нур Алем", "Дворец мира и согласия", "Ак Орда",
    "Аэропорт Нурсултан Назарбаев", "Вокзал Нурлы Жол", "Астана Опера", "Мечеть Хазрет Султан",
    "Монумент «Казак Ели»", "Дворец творчества «Шабыт»", "Центральный концертный зал «Казахстан»",
    "Национальный музей Республики Казахстан", "Центральный парк", "Этнопарк «Атамекен»",
]
LANDMARK_CATEGORIES = {"attraction", "monument", "viewpoint", "museum", "mall", "theatre", "gallery", "park"}


class PhotoError(ValueError):
    pass


class PhotoGuess(BaseModel):
    landmark: str | None = None
    confidence: str = "low"
    seen: str = ""


def prepare_image(data: bytes, content_type: str | None) -> str:
    """bytes → data URL с JPEG без EXIF, длинная сторона ≤ 1024 px."""
    if content_type and content_type not in ALLOWED_TYPES:
        raise PhotoError("Поддерживаются JPEG, PNG, WEBP")
    if len(data) > MAX_BYTES:
        raise PhotoError("Фото больше 8 МБ")
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")  # новый объект без EXIF/метаданных
    except (UnidentifiedImageError, OSError) as e:
        raise PhotoError("Не удалось прочитать изображение") from e
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def candidate_names(limit: int = 150) -> list[str]:
    names = list(KNOWN_LANDMARKS)
    pois = [p for p in rag.all_pois() if p.get("category") in LANDMARK_CATEGORIES]
    pois.sort(key=lambda p: (p.get("description_source") != "wikipedia", -(p.get("rating") or 0)))
    for p in pois:
        if p["name"] not in names:
            names.append(p["name"])
    return names[:limit]


def identify_landmark(image_data_url: str, user_text: str = "") -> PhotoGuess:
    names = candidate_names()
    content = [
        {"type": "text", "text": "Список мест:\n" + "\n".join(f"- {n}" for n in names)
         + (f"\n\nКомментарий пользователя: <user_query>{user_text}</user_query>" if user_text else "")},
        {"type": "image_url", "image_url": {"url": image_data_url, "detail": "low"}},
    ]
    data = llm.chat_json(PROMPT, content, role="fast", name="photo-landmark")
    if not data:
        return PhotoGuess()
    try:
        guess = PhotoGuess.model_validate(data)
    except ValueError:
        return PhotoGuess()
    if guess.landmark and guess.landmark not in names:  # только из закрытого списка
        guess.landmark = None
    if guess.confidence not in {"high", "medium", "low"}:
        guess.confidence = "low"
    return guess


def resolve(guess: PhotoGuess) -> dict | None:
    """PhotoGuess → {"lat","lon","label"} или None, если не уверены или нет координат."""
    if not guess.landmark or guess.confidence == "low":
        return None
    name = guess.landmark.replace("EXPO / ", "").strip()
    return rag.resolve_landmark(guess.landmark) or rag.resolve_landmark(name)
