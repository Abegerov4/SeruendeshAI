"""Recalculate exact published coverage and write the user's Markdown/JSON report."""
from collections import Counter
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from data.snapshot import resolve_snapshot
from data.place_details import load_place_details, apply_place_details
from data.eligibility import apply_fact_reviews
from data.catalog_audit import applicable_fields
from ayat_backend.app.team_data import load_team_snapshot
from ayat_backend.app.evidence import price_benchmarks

ROOT=Path.cwd()
OUT=ROOT/"data/review/2026-10-19-refresh"
RUN=ROOT/"eval/runs/2026-10-19-catalog-refresh"


def read(path, default=None):
    return json.loads(path.read_bytes()) if path.exists() else default


def encode(value):
    return json.dumps(value,ensure_ascii=False,indent=2)+"\n"


def main():
    handle=resolve_snapshot(ROOT/"data/processed")
    raw=(handle.path/"pois.json").read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    today=datetime.now(ZoneInfo("Asia/Almaty")).date()
    baseline=json.loads(raw)
    details=load_place_details(handle.path/"place_details.json",canonical_sha256=digest,as_of=today)
    rows=apply_place_details(baseline,details)
    reviews=read(handle.path/"fact_reviews.json",{})
    if reviews:
        rows=apply_fact_reviews(rows,reviews,canonical_sha256=digest)
    pois,gaz,view=load_team_snapshot(handle.path/"pois.json",quarantine_path=handle.path/"quarantine.json")
    by_id={r["id"]:r for r in gaz}
    active_ids={p["id"] for p in pois}
    quarantine=read(handle.path/"quarantine.json",[])
    closed={r["id"] for r in quarantine if r.get("reason_code")=="confirmed_permanent_closure"}
    moved={r["id"] for r in quarantine if r.get("reason_code")=="service_catalog_only"}
    gaps, counts, denominators, food_counts = [],Counter(),Counter(),Counter()
    reviewed_prior={r["canonical_id"] for r in reviews.get("reviews",[]) if r.get("status")=="accepted"}
    for row in rows:
        derived=by_id.get(row["id"],row)
        facts=(derived.get("place_details") or {}).get("facts",[])
        values={f["field"]:f["value"] for f in facts}
        values={**derived,**values}
        values["source_description"]=row.get("description") if row.get("description_kind")=="source" else None
        values["menu_url"]=values.get("menu_url") or (row.get("raw_tags") or {}).get("website:menu")
        for f in facts:
            if f["field"] in {"cuisine","cuisines"}:
                values["cuisine"]=f["value"]
        prices=(derived.get("place_details") or {}).get("prices",[])
        menus=(derived.get("place_details") or {}).get("menu_items",[])
        if prices or any(m.get("price") for m in menus):
            values["price_range"]="source-bound price; channels separate"
        missing=[]
        for field in applicable_fields(row):
            denominators[field]+=1
            if values.get(field) is None or values.get(field)=="" or values.get(field)==[]:
                missing.append(field)
                counts[field]+=1
        if row["category"] in {"cafe","restaurant","bar","nightlife"}:
            food_counts["branches"]+=1
            if menus:food_counts["branches_with_menu_items"]+=1
            if any(p["kind"]=="average_check" for p in prices):food_counts["branches_with_average_check"]+=1
        gaps.append({"canonical_id":row["id"],"name":row["name"],"category":row["category"],
            "active_recommendation":row["id"] in active_ids,"archived_closed":row["id"] in closed,
            "missing_applicable_fields":sorted(missing),"has_reviewed_rich_facts":row["id"] in details,
            "missing_basic_visit_data":all(not values.get(k) for k in ("address","phone","website","opening_hours")),
            "has_prior_accepted_review":row["id"] in reviewed_prior})
    audit=read(RUN/"source-audit/summary.json",{})
    services=read(handle.path/"city_services.json",{})
    new_reviewed=set(details)|closed|moved
    all_reviewed=new_reviewed|reviewed_prior
    queue_events=[]
    for line in (OUT/"discovery-queue-events.jsonl").read_text().splitlines() if (OUT/"discovery-queue-events.jsonl").exists() else []:
        try:queue_events.append(json.loads(line))
        except ValueError:pass
    summary={"generated_at":datetime.now(ZoneInfo("Asia/Almaty")).isoformat(),"snapshot_version":handle.version,
        "canonical_sha256":digest,"canonical_records":len(rows),"preserved_source_ids":view["preserved_source_ids_count"],
        "active_recommendation_records":len(pois),"active_origin_records":len(gaz),
        "records_missing_any_applicable_field":sum(bool(r["missing_applicable_fields"]) for r in gaps),
        "without_new_reviewed_rich_facts":len(rows)-len(details),
        "without_reviewed_confirmation_this_refresh":len(rows)-len(new_reviewed),
        "without_any_curated_review_including_prior":len(rows)-len(all_reviewed),
        "no_data_after_completed_search":0,"completed_exhaustive_searches":0,
        "new_confirmed_closed_exclusions":len(closed),"new_rich_branches":len(details),
        "service_offers_moved_to_service_catalog":len(moved),
        "without_address_phone_website_hours":sum(r["missing_basic_visit_data"] for r in gaps),
        "rich_counts":{k:sum(len(r[k]) for r in details.values()) for k in ("facts","menu_items","prices")},
        "menu_price_channels":dict(Counter((m.get("price") or {}).get("channel","unknown_full_price") for r in details.values() for m in r["menu_items"])),
        "menu_branches":sum(bool(r["menu_items"]) for r in details.values()),"food_coverage":dict(food_counts),
        "services":len(services.get("services",[])),"operators":len(services.get("operators",[])),
        "dated_departures":sum(len(s["dated_departures"]) for s in services.get("services",[])),
        "price_benchmarks_expo":price_benchmarks(pois,(51.092788,71.421482),today),
        "field_missing_counts":dict(counts),"field_applicable_denominators":dict(denominators),
        "source_audit":{k:audit.get(k) for k in ("network_pass_status","target_urls","known_url_targets_with_bounded_outcomes",
            "deferred_retry_count","fetch_statuses","fresh_exact_branch_identity_rows","incomplete_branch_checks_rows",
            "fetched_sources_without_branch_match_rows","listed_website_rows")},
        "discovery_queue":{"events":len(queue_events),"actual_requests":sum(e.get("actual_request",False) for e in queue_events),
            "outcomes":dict(Counter(e["outcome"] for e in queue_events)),"rows_with_events":len({e["canonical_id"] for e in queue_events})},
        "validation":read(RUN/"verification.json",{"status":"final verification pending"})}
    (OUT/"refresh-summary.json").write_text(encode(summary))
    with (OUT/"record-gaps.jsonl").open("w") as f:
        for row in gaps:f.write(json.dumps(row,ensure_ascii=False)+"\n")
    field_table="\n".join(f"| {k} | {counts[k]:,} | {denominators[k]:,} |" for k in sorted(denominators))
    price_table="\n".join(f"| {k} | {v['n']} | {v['mean']:g} | {v['median']:g} | {v['q25']:g} |" for k,v in summary["price_benchmarks_expo"].items())
    body=f"""# Обновление базы Smart City: результат и оставшиеся проблемы

Дата отчёта: {summary['generated_at']}. Локальная версия: `{handle.version}`.

## Что выполнено

Аудит охватил **{len(rows):,} исходных записей**. В приложение опубликованы дополнительные проверенные сведения для **{len(details)} записей конкретных мест и услуг**: {summary['rich_counts']['facts']} фактов, {summary['rich_counts']['menu_items']} позиций меню и {summary['rich_counts']['prices']} средних чеков. Отдельно подключены {summary['services']} экскурсионных услуг, включая маршруты RedBus, операторы, посадка и тарифы. Сохранены все {view['preserved_source_ids_count']:,} исходных идентификаторов.

Это **частичное обогащение всего проверенного каталога**, а не заявление, что все заведения независимо проверены или что весь интернет просмотрен. Полнота автоматического аудита и полнота подтверждённых фактов считаются отдельно.

## Сколько неполных и неподтверждённых записей

| Показатель | Количество |
|---|---:|
| Исходный каталог, включая архив исключений | {len(rows):,} |
| Места в активных рекомендациях и карте | {len(pois):,} |
| Записи с хотя бы одним пробелом по расширенной применимой схеме | {summary['records_missing_any_applicable_field']:,} |
| Без новых проверенных подробных сведений | {summary['without_new_reviewed_rich_facts']:,} |
| Нет адреса, телефона, сайта и часов одновременно | {summary['without_address_phone_website_hours']:,} |
| Без проверенного подтверждения в этом обновлении, с учётом закрытий | {summary['without_reviewed_confirmation_this_refresh']:,} |
| Без какого-либо принятого ручного обзора, включая предыдущую проверку | {summary['without_any_curated_review_including_prior']:,} |
| Доказанно «нет информации после завершённого полного поиска» | 0 |
| Завершён полный поиск по всем источникам для филиала | 0 |
| Новые исключения по явному сообщению о постоянном закрытии | {len(closed)} |

«Неполная» запись может содержать правильные название, адрес и телефон, но не иметь подтверждения доступности или меню. Это не означает, что о ней ничего не известно. Число «нет информации» нельзя подменять количеством непроверенных записей. В текущей выдаче {len(pois):,} мест; остальные записи полного каталога преимущественно относятся к типам, не используемым для досуга.

Для каждой из {len(rows):,} записей сохранены ID, название, категория и точные пробелы: [record-gaps.jsonl](../data/review/2026-10-19-refresh/record-gaps.jsonl). Сводка для программ: [refresh-summary.json](../data/review/2026-10-19-refresh/refresh-summary.json).

## Фактический обход источников

Из {audit.get('target_urls')} различных известных адресов получены ограниченные по времени результаты для {audit.get('known_url_targets_with_bounded_outcomes')}; {audit.get('deferred_retry_count')} повторных проверок WhatsApp остались незавершёнными после повторяющихся ошибок. Успешных HTTP-загрузок: {audit.get('fetch_statuses',{}).get('successful_fetch')}. Успешная загрузка страницы не доказывает существование именно нужного филиала.

Автоматический обход нашёл {audit.get('fresh_exact_branch_identity_rows')} точных совпадений идентичности; {audit.get('fetched_sources_without_branch_match_rows')} записей имеют загруженные источники без точного совпадения; {audit.get('incomplete_branch_checks_rows')} проверок филиалов остались незавершёнными. После отдельной проверки 65 из 67 совпадений приняты, два удержаны: Eltaim с неполным адресом, Tehnoinvest с недостаточно подтверждёнными сведениями только в JSON-LD. Эти числа относятся к автоматическому обходу; дополнительные 2ГИС, меню и ручные проверки учтены в обогащении отдельно.

Текущий публичный OSM API не удалось получить для 5 807 исходных объектов: ошибки источников сохранены. Исторический PBF от 17 октября не считается новой проверкой работы предприятий. Для 1 091 заведений питания без сайта запущена отдельная очередь поиска 2ГИС/Bing; Яндекс/Google возвращали 429, DuckDuckGo — проверку человека. Ошибки не обходятся через скрытые API или аккаунты. Контрольная точка очереди и фактические попытки для репозитория: [discovery-checkpoint-summary.json](../data/review/2026-10-19-refresh/discovery-checkpoint-summary.json), [discovery-checkpoint-events.jsonl](../data/review/2026-10-19-refresh/discovery-checkpoint-events.jsonl). Живой журнал и сырые HTTP-кэши продолжают храниться локально; они исключены из Git. Найденные кандидаты не становятся фактами без отдельной проверки.

Полная методика, результаты по категориям и доказательства: [audit-report.md](../data/review/2026-10-19-refresh/audit-report.md), [audit-method.md](../data/review/2026-10-19-refresh/audit-method.md).

## Закрытые филиалы

1. **Tary, Сыганак 17ф**: [2ГИС](https://2gis.kz/astana/search/Tary) явно помечает этот адрес как закрытый. Ответ 410 карточки сам по себе не использован как доказательство закрытия.
2. **Joule 27, Мангилик Ел 57А**: [Яндекс Карты](https://yandex.kz/maps/ru/org/joule_27/127662901008/) сообщают о прекращении работы; совпали название, адрес и телефон.

Оба исключены из активных рекомендаций, карты, индекса и определения текущего местоположения по названию. Исходные записи и причины сохранены: [closed-branches.json](../data/review/2026-10-19-refresh/closed-branches.json). Неполные данные сами по себе не использованы как основание закрытия или удаления.

Ещё три записи услуг (RedBus, общая экскурсия Астана Опера и теплоходная прогулка CityPass) перенесены из обычных POI в каталог услуг. Они не считаются закрытыми и больше не предлагаются как 15-минутные остановки для фотографии. Здание театра сохранено отдельно; два различных театральных продукта и разные речные программы не объединены.

## Заполненность после наложения принятых сведений

Поля считаются по применимости. Для питания нужны кухня, меню и цена; для парка меню неприменимо. Исходное описание отличается от автоматически созданного шаблона. Базовые сведения из старых источников учитываются как наличие значения, но не считаются новой независимой проверкой.

| Поле | Не заполнено | Применимых записей |
|---|---:|---:|
{field_table}

## Цены и меню

Цена сохраняет валюту, единицу, канал и источник. Меню доставки отдельно от меню в зале; средний чек отдельно от цены конкретного блюда. Неполные базовые цены конструкторов не выдаются как полная стоимость обеда. Меню может меняться после проверки.

Статистика по опубликованным в 2ГИС средним чекам в радиусе 5 км от EXPO:

| Сопоставимая группа | Филиалов | Среднее, ₸ | Медиана, ₸ | Нижний квартиль, ₸ |
|---|---:|---:|---:|---:|
{price_table}

Бургерная с одним наблюдением не смешивается с ресторанами или кофейнями. Выборка небольшая, собрана по доступным источникам и не представляет весь город. Средний чек не позволяет вывести стоимость порции пюре с котлетой. Для качественного запроса «дёшево» код сравнивает чек только внутри группы с минимум восемью наблюдениями; для конкретного блюда требует его собственную цену. У Gasteria меню опубликовано на сайте заведения; дата версии источника 14 апреля 2026 года сохраняется отдельно от даты получения страницы.

## Что исправлено в ответах ИИ

- Названные блюда, кухня, диета и бюджет сохраняются как отдельные ограничения; модель не может удалить явное условие пользователя.
- Одно опубликованное предложение должно одновременно подтверждать блюдо, диету и бюджет. Нельзя соединить дешёвый куриный суп с дорогим веганским супом.
- Меню доставки не подтверждает наличие блюда для посещения в зале. При отсутствии подтверждения сначала говорится об этом и предлагается ослабить запрос.
- Просьба «поближе» сохраняет предыдущие ограничения еды; новый запрос про парк или музей их сбрасывает.
- Часы доставки не превращаются в часы посещения. Спорные часы и удобства удерживаются до разрешения конфликта.
- В RedBus посадка, посещение и проезд мимо имеют разные роли. Маршруты доступны в ответе и карточке.
- Получение страницы сегодня не делает актуальным старое расписание без года. Отправлений на полную текущую дату подтверждено: {summary['dated_departures']}.
- У фактов и цен проверяются давность, период действия, источник и конкретный филиал. Противоречивые тарифы не выдаются как подтверждённые.
- Новые сведения публикуются с неизменённым исходным каталогом и согласованным локальным индексом. При обновлении переносится только проверка полностью неизменившейся исходной записи; изменившиеся остаются в истории до повторного обзора.

## Оставшиеся проблемы и лучшие следующие действия

| Проблема | Решение | Состояние |
|---|---|---|
| Большинство филиалов ещё не имеют нового независимого обзора | Продолжать очередь по названию, дому, координатам и телефону; принимать только точные совпадения | Осталось; точные количества выше |
| Публичные карты ограничивают массовый доступ | Использовать доступные открытые страницы; для полного покрытия нужен разрешённый экспорт/доступ поставщика либо отдельная ручная проверка | Ограничение источников; новых платных доступов не покупали |
| Меню и цены покрывают лишь часть заведений | Собирать полные доступные меню владельцев; разделять доставку/зал; хранить даты версии и проверять изменения | Частично выполнено |
| Часы, доступность, Wi-Fi, розетки и детские условия часто неизвестны | Отдельные проверяемые поля и свидетельства; отсутствие данных не заменять признаками категории | Схема и удержание неизвестного готовы; сбор продолжается |
| Сведения об адресе не гарантируют правильные координаты | Сопоставлять точку входа/посадки с точной карточкой; исправлять геометрию отдельным принятым обзором | Точка колеса Ailand исправлена с сохранением исходной; [coordinate-review.json](../data/review/2026-10-19-refresh/coordinate-review.json) |
| Нет расписания RedBus на текущую полную дату | Обновлять по датированным объявлениям организатора; не переносить старую неделю на сегодня | Честный unknown |
| Статистика цен смещена к доступным заведениям | Расширять выборку столовых, фастфуда и районов; считать медиану/квартили отдельно по формату и каналу | Текущая ограниченная выборка опубликована |
| Не установлено отсутствие информации по всем источникам | Не удалять по 404/таймауту; фиксировать полный список попыток и отдельное решение о завершении поиска | Массовых удалений по отсутствию данных нет |
| Изменение сведений со временем | Повторный сбор с кешем и продолжением; отдельные сроки старения цен/фактов и история | Реализованы механизмы; постоянное расписание обновлений не развёрнуто |

## Проверки и запуск

Итоговые результаты тестов и реальной проверки модели: [verification.json](../eval/runs/2026-10-19-catalog-refresh/verification.json). Бюджет LLM/embeddings общий $0,10; локальный e5 не вызывает платный API. Учёт реальных вызовов: [provider-cost.json](../eval/runs/2026-10-19-remediation/provider-cost.json). Внешняя почта отключена.

Локальный запуск: `scripts/run_local_integration.sh`, адрес `http://127.0.0.1:8001`. Этот профиль использует реальные данные и серверные шаблоны; оплачиваемая модель проверяется отдельным ограниченным прогоном.

Проверочные запросы: «Я рядом с EXPO, пюре с котлетой очень дёшево»; затем «Поближе пожалуйста»; «Просто где поесть рядом»; «Какой маршрут у RedBus?»; «Где сесть на RedBus?»; «Последний рейс RedBus сегодня во сколько?». Отсутствие подтверждения блюда или расписания должно быть явно названо.
"""
    body=re.sub(r"\b\d{1,3}(?:,\d{3})+\b",lambda m:m.group().replace(",","\u202f"),body)
    (ROOT/"docs/catalog_refresh_2026-10-19.md").write_text(body)
    print(json.dumps({k:summary[k] for k in ("snapshot_version","canonical_records","new_rich_branches","rich_counts",
        "records_missing_any_applicable_field","without_new_reviewed_rich_facts","new_confirmed_closed_exclusions")},ensure_ascii=False))


if __name__=="__main__":main()
