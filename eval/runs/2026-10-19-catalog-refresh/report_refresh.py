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
from data.meal_cost import complete_meal_price
from ayat_backend.app.team_data import load_team_snapshot
from ayat_backend.app.evidence import price_benchmarks

ROOT=Path.cwd()
OUT=ROOT/"data/review/2026-10-19-refresh"
RUN=ROOT/"eval/runs/2026-10-19-catalog-refresh"
FOOD_RUN=ROOT/"eval/runs/2026-10-19-food-service"


def read(path, default=None):
    return json.loads(path.read_bytes()) if path.exists() else default


def encode(value):
    return json.dumps(value,ensure_ascii=False,indent=2)+"\n"


def verification_reports(snapshot_version):
    """Keep final and partial verification attached to the snapshot it tested."""
    final_reports=[]
    for path in (FOOD_RUN/"verification.json",RUN/"verification.json"):
        payload=read(path)
        if payload is not None:
            final_reports.append({"path":str(path.relative_to(ROOT)),
                "snapshot_version":payload.get("snapshot_version"),"report":payload})
    current=next((r for r in final_reports if r["snapshot_version"]==snapshot_version),None)
    evidence={}
    for key,filename in (("source_index","source-index-verification.json"),
                         ("provider_off_runtime","offline-runtime.json")):
        path=FOOD_RUN/filename
        payload=read(path,{})
        if payload.get("snapshot_version")==snapshot_version:
            evidence[key]={"path":str(path.relative_to(ROOT)),"snapshot_version":snapshot_version,
                "passed":payload.get("passed")}
            if key=="provider_off_runtime":
                evidence[key].update(cases=len(payload.get("results",[])),
                    external_paid_calls=payload.get("external_paid_calls"),execution_kind=payload.get("execution_kind"))
    return {"validation":current["report"] if current else {
                "status":"final verification pending","snapshot_version":snapshot_version},
        "validation_report":current["path"] if current else None,
        "prior_validations":[r for r in final_reports if r["snapshot_version"]!=snapshot_version],
        "current_verification_evidence":evidence}


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
    classification_held={r["id"] for r in quarantine if r.get("reason_code")=="source_classification_conflict"}
    gaps, counts, denominators, food_counts = [],Counter(),Counter(),Counter()
    for key in ("branches","branches_with_menu_items","branches_with_average_check",
                "branches_with_kitchen_hours","branches_with_complete_meal_cost"):
        food_counts[key]=0
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
        food_service_missing=[]
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
            if any(f["field"]=="kitchen_hours" for f in facts):
                food_counts["branches_with_kitchen_hours"]+=1
            else:
                food_service_missing.append("kitchen_hours")
            if any(complete_meal_price(m,today) is not None for m in menus):
                food_counts["branches_with_complete_meal_cost"]+=1
            else:
                food_service_missing.append("complete_meal_cost")
        gaps.append({"canonical_id":row["id"],"name":row["name"],"category":row["category"],
            "canonical_category":row.get("canonical_category",row["category"]),
            "active_recommendation":row["id"] in active_ids,"archived_closed":row["id"] in closed,
            "missing_applicable_fields":sorted(missing),"has_reviewed_rich_facts":row["id"] in details,
            "missing_food_service_fields":food_service_missing,
            "missing_basic_visit_data":all(not values.get(k) for k in ("address","phone","website","opening_hours")),
            "has_prior_accepted_review":row["id"] in reviewed_prior})
    audit=read(RUN/"source-audit/summary.json",{})
    services=read(handle.path/"city_services.json",{})
    new_reviewed=set(details)|closed|moved|classification_held
    all_reviewed=new_reviewed|reviewed_prior
    queue_events=[]
    event_path=OUT/"discovery-checkpoint-events.jsonl"
    if not event_path.exists():
        event_path=OUT/"discovery-queue-events.jsonl"
    for line in event_path.read_text().splitlines() if event_path.exists() else []:
        try:queue_events.append(json.loads(line))
        except ValueError:pass
    discovery=read(OUT/"discovery-checkpoint-summary.json",{})
    branch_reviews=read(OUT/"discovery-followup-branch-reviews.json",{})
    followup=read(OUT/"discovery-followup-extraction.json",{})
    menus=[m for r in details.values() for m in r["menu_items"]]
    classification=read(ROOT/"data/review/2026-10-19-food-service/classification-review.json",{})
    rows_by_id={r["id"]:r for r in rows}
    food_category_ids={r["canonical_id"] for r in classification.get("reviews",[])
        if classification.get("canonical_sha256")==digest and r.get("status")=="accepted"
        and r.get("field")=="category" and r.get("canonical_id") in rows_by_id
        and rows_by_id[r["canonical_id"]]["category"]==r.get("value")
        and rows_by_id[r["canonical_id"]].get("canonical_category")!=r.get("value")}
    verification=verification_reports(handle.version)
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
        "source_classification_conflict_exclusions":len(classification_held),
        "without_address_phone_website_hours":sum(r["missing_basic_visit_data"] for r in gaps),
        "rich_counts":{k:sum(len(r[k]) for r in details.values()) for k in ("facts","menu_items","prices")},
        "menu_price_channels":dict(Counter((m.get("price") or {}).get("channel","unknown_full_price") for r in details.values() for m in r["menu_items"])),
        "menu_branches":sum(bool(r["menu_items"]) for r in details.values()),"food_coverage":dict(food_counts),
        "food_service":{"classification_corrections":len(food_category_ids),
            "dine_in_menu_items":sum((m.get("price") or {}).get("channel")=="dine_in" for m in menus),
            "partial_cost_menu_items":sum(m.get("cost",{}).get("complete") is False for m in menus),
            "complete_cost_menu_items":sum(complete_meal_price(m,today) is not None for m in menus),
            "kitchen_hour_branches":sum(any(f["field"]=="kitchen_hours" for f in r["facts"]) for r in details.values()),
            "branches_missing_kitchen_hours":sum("kitchen_hours" in r["missing_food_service_fields"] for r in gaps),
            "branches_without_complete_meal_cost":sum("complete_meal_cost" in r["missing_food_service_fields"] for r in gaps)},
        "services":len(services.get("services",[])),"operators":len(services.get("operators",[])),
        "dated_departures":sum(len(s["dated_departures"]) for s in services.get("services",[])),
        "price_benchmarks_expo":price_benchmarks(pois,(51.092788,71.421482),today),
        "field_missing_counts":dict(counts),"field_applicable_denominators":dict(denominators),
        "source_audit":{k:audit.get(k) for k in ("network_pass_status","target_urls","known_url_targets_with_bounded_outcomes",
            "deferred_retry_count","fetch_statuses","fresh_exact_branch_identity_rows","incomplete_branch_checks_rows",
            "fetched_sources_without_branch_match_rows","listed_website_rows")},
        "discovery_queue":{"pass_status":discovery.get("pass_status","in_progress"),
            "launch_rows":discovery.get("rows"),"events":len(queue_events),
            "actual_requests":sum(e.get("actual_request",False) for e in queue_events),
            "outcomes":dict(Counter(e["outcome"] for e in queue_events)),"rows_with_events":len({e["canonical_id"] for e in queue_events}),
            "branch_fact_verification_complete":False,
            "reviewed_nearby_candidates":len(branch_reviews.get("decisions",[])),
            "accepted_followup_branches":followup.get("accepted_additive_records",0)},
        **verification}
    (OUT/"refresh-summary.json").write_text(encode(summary))
    with (OUT/"record-gaps.jsonl").open("w") as f:
        for row in gaps:f.write(json.dumps(row,ensure_ascii=False)+"\n")
    field_table="\n".join(f"| {k} | {counts[k]:,} | {denominators[k]:,} |" for k in sorted(denominators))
    price_table="\n".join(f"| {k} | {v['n']} | {v['mean']:g} | {v['median']:g} | {v['q25']:g} |" for k,v in summary["price_benchmarks_expo"].items())
    closure_table="\n".join(f"| {r.get('source_name',r['id'])} | {r.get('source_address','')} | [источник]({r['evidence_urls'][0]}) — {r.get('evidence_excerpt','явное сообщение о закрытии')} |"
        for r in quarantine if r.get("reason_code")=="confirmed_permanent_closure")
    queue_state=("завершён ограниченный проход поиска" if discovery.get("pass_status")=="bounded_discovery_pass_finished"
                 else "запущена отдельная очередь поиска")
    current_validation_text=(f"Итоговая проверка текущего снимка `{handle.version}`: "
        f"[verification.json](../{summary['validation_report']})." if summary["validation_report"] else
        f"Полная итоговая верификация текущего снимка `{handle.version}` ещё не записана; старые результаты не считаются его проверкой.")
    evidence_labels={"source_index":"источники и индекс","provider_off_runtime":"HTTP без внешних провайдеров"}
    current_evidence_text=" ".join(f"[{evidence_labels[key]}](../{value['path']}) — "
        f"{'пройдено' if value['passed'] is True else 'не пройдено' if value['passed'] is False else 'результат не указан'}"
        f"{'; сценариев: '+str(value['cases']) if 'cases' in value else ''}."
        for key,value in summary["current_verification_evidence"].items())
    prior_validation_text=" ".join(f"[Итоговая проверка `{r['snapshot_version'] or 'без указанного снимка'}`](../{r['path']}) "
        "сохранена как историческое свидетельство и не относится к текущему снимку." for r in summary["prior_validations"])
    body=f"""# Обновление базы Smart City: результат и оставшиеся проблемы

Дата отчёта: {summary['generated_at']}. Локальная версия: `{handle.version}`.

## Что выполнено

Аудит охватил **{len(rows):,} исходных записей**. В приложение опубликованы дополнительные проверенные сведения для **{len(details)} записей конкретных мест и услуг**: {summary['rich_counts']['facts']} фактов, {summary['rich_counts']['menu_items']} позиций меню и {summary['rich_counts']['prices']} средних чеков. Отдельно подключены {summary['services']} экскурсионных услуг, включая маршруты RedBus, операторы, посадка и тарифы. Сохранены все {view['preserved_source_ids_count']:,} исходных идентификаторов.

Текущий пакет питания добавил основное меню Italio, отдельные часы кухни Coffee Hub и {summary['food_service']['classification_corrections']} подтверждённых исправлений категорий филиалов. Категории в отчёте и списке пробелов учитывают принятые наложения; исходные категории сохранены отдельно. Подробности, удержанные сведения и ограничения: [food_service_2026-10-19.md](food_service_2026-10-19.md).

Это **частичное обогащение всего проверенного каталога**, а не заявление, что все заведения независимо проверены или что весь интернет просмотрен. Полнота автоматического аудита и полнота подтверждённых фактов считаются отдельно.

## Сколько неполных и неподтверждённых записей

| Показатель | Количество |
|---|---:|
| Исходный каталог, включая архив исключений | {len(rows):,} |
| Места в активных рекомендациях и карте | {len(pois):,} |
| Записи, доступные как ориентиры текущего местоположения | {len(gaz):,} |
| Записи с хотя бы одним пробелом по расширенной применимой схеме | {summary['records_missing_any_applicable_field']:,} |
| Без новых проверенных подробных сведений | {summary['without_new_reviewed_rich_facts']:,} |
| Нет адреса, телефона, сайта и часов одновременно | {summary['without_address_phone_website_hours']:,} |
| Без проверенного подтверждения в этом обновлении, с учётом закрытий | {summary['without_reviewed_confirmation_this_refresh']:,} |
| Без какого-либо принятого ручного обзора, включая предыдущую проверку | {summary['without_any_curated_review_including_prior']:,} |
| Доказанно «нет информации после завершённого полного поиска» | 0 |
| Завершён полный поиск по всем источникам для филиала | 0 |
| Новые исключения по явному сообщению о постоянном закрытии | {len(closed)} |
| Исключено из рекомендаций из-за подтверждённого конфликта категории, без закрытия | {len(classification_held)} |

«Неполная» запись может содержать правильные название, адрес и телефон, но не иметь подтверждения доступности или меню. Это не означает, что о ней ничего не известно. Число «нет информации» нельзя подменять количеством непроверенных записей. В текущей выдаче {len(pois):,} мест; остальные записи полного каталога преимущественно относятся к типам, не используемым для досуга.

Для каждой из {len(rows):,} записей сохранены ID, название, исходная и принятая категории, точные пробелы основной схемы и отдельные неизвестные условия питания: [record-gaps.jsonl](../data/review/2026-10-19-refresh/record-gaps.jsonl). Сводка для программ: [refresh-summary.json](../data/review/2026-10-19-refresh/refresh-summary.json).

## Фактический обход источников

Из {audit.get('target_urls')} различных известных адресов получены ограниченные по времени результаты для {audit.get('known_url_targets_with_bounded_outcomes')}; {audit.get('deferred_retry_count')} повторных проверок WhatsApp остались незавершёнными после повторяющихся ошибок. Успешных HTTP-загрузок: {audit.get('fetch_statuses',{}).get('successful_fetch')}. Успешная загрузка страницы не доказывает существование именно нужного филиала.

Автоматический обход нашёл {audit.get('fresh_exact_branch_identity_rows')} точных совпадений идентичности; {audit.get('fetched_sources_without_branch_match_rows')} записей имеют загруженные источники без точного совпадения; {audit.get('incomplete_branch_checks_rows')} проверок филиалов остались незавершёнными. После отдельной проверки 65 из 67 совпадений приняты, два удержаны: Eltaim с неполным адресом, Tehnoinvest с недостаточно подтверждёнными сведениями только в JSON-LD. Эти числа относятся к автоматическому обходу; дополнительные 2ГИС, меню и ручные проверки учтены в обогащении отдельно.

Текущий публичный OSM API не удалось получить для 5 807 исходных объектов: ошибки источников сохранены. Исторический PBF от 17 октября не считается новой проверкой работы предприятий. Для {discovery.get('rows',1091)} заведений питания без сайта {queue_state} 2ГИС/Bing: {summary['discovery_queue']['actual_requests']} фактических запросов, {summary['discovery_queue']['outcomes'].get('incomplete_source_error',0)} ошибок источников. Яндекс/Google возвращали 429, DuckDuckGo — проверку человека; блокировки не обходились. Проход двух источников не является полной независимой проверкой филиала: все записи сохраняют незавершённый статус по политике третьего источника, а число доказанных случаев «информации нет» остаётся нулевым. Отдельно рассмотрены {summary['discovery_queue']['reviewed_nearby_candidates']} близких кандидатов; принято {summary['discovery_queue']['accepted_followup_branches']} дополнительных уникальных филиалов. Контрольная точка и фактические попытки: [discovery-checkpoint-summary.json](../data/review/2026-10-19-refresh/discovery-checkpoint-summary.json), [discovery-checkpoint-events.jsonl](../data/review/2026-10-19-refresh/discovery-checkpoint-events.jsonl). Исходный журнал и сырые HTTP-кэши хранятся локально и исключены из Git. Найденные кандидаты не становятся фактами без отдельной проверки.

Полная методика, результаты по категориям и доказательства: [audit-report.md](../data/review/2026-10-19-refresh/audit-report.md), [audit-method.md](../data/review/2026-10-19-refresh/audit-method.md).

## Закрытые филиалы

| Филиал | Адрес | Прямое свидетельство |
|---|---|---|
{closure_table}

Все {len(closed)} филиала исключены из активных рекомендаций, карты, индекса и определения текущего местоположения по названию. Исходные записи и причины сохранены: [closed-branches.json](../data/review/2026-10-19-refresh/closed-branches.json). Неполные данные сами по себе не использованы как основание закрытия или удаления.

Loft Park удержан из рекомендаций из-за отдельного конфликта категории: точная карточка 2ГИС относит его только к лотерейным клубам, а исходный каталог — к кафе. Это не закрытие; исходная запись и возможность использовать место как ориентир сохранены. Решения и доказательства: [discovery-followup-dispositions.json](../data/review/2026-10-19-refresh/discovery-followup-dispositions.json).

Ещё три записи услуг (RedBus, общая экскурсия Астана Опера и теплоходная прогулка CityPass) перенесены из обычных POI в каталог услуг. Они не считаются закрытыми и больше не предлагаются как 15-минутные остановки для фотографии. Здание театра сохранено отдельно; два различных театральных продукта и разные речные программы не объединены.

## Заполненность после наложения принятых сведений

Поля считаются по применимости. Для питания нужны кухня, меню и цена; для парка меню неприменимо. Исходное описание отличается от автоматически созданного шаблона. Базовые сведения из старых источников учитываются как наличие значения, но не считаются новой независимой проверкой.

| Поле | Не заполнено | Применимых записей |
|---|---:|---:|
{field_table}

## Цены и меню

Цена сохраняет валюту, единицу, канал и источник. Меню доставки отдельно от меню в зале; средний чек отдельно от цены конкретного блюда. Неполные базовые цены конструкторов не выдаются как полная стоимость обеда. Меню может меняться после проверки.

В текущем снимке меню есть у {summary['menu_branches']} филиалов; {summary['food_service']['dine_in_menu_items']} позиций относятся к залу. У {summary['food_service']['partial_cost_menu_items']} позиций подтверждена часть условий оплаты; подтверждённых полных итогов с учётом всех обязательных платежей — {summary['food_service']['complete_cost_menu_items']}. Отдельные часы кухни есть у {summary['food_service']['kitchen_hour_branches']} филиала. Из {food_counts['branches']:,} записей питания у {summary['food_service']['branches_missing_kitchen_hours']:,} не подтверждены часы кухни и у {summary['food_service']['branches_without_complete_meal_cost']:,} нет предложения с подтверждённым полным итогом. Эти пробелы рассчитаны отдельно от основной схемы выше; они не означают, что заведение закрыто или о нём нет информации.

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

{current_validation_text}

Отдельные проверки, привязанные к текущему снимку: {current_evidence_text or 'ещё не записаны.'}

{prior_validation_text}

Четыре реальные проверки внешней модели относятся к предыдущей версии `b479f2445492454782a09e8d95495ae7`; они не переименованы в проверку нового снимка. Текущий пакет проверяется локально с отключёнными провайдерами. Бюджет LLM/embeddings общий $0,10; локальный e5 не вызывает платный API. Учёт реальных вызовов: [provider-cost.json](../eval/runs/2026-10-19-remediation/provider-cost.json). Внешняя почта отключена.

Локальный запуск: `scripts/run_local_integration.sh`, адрес `http://127.0.0.1:8001`. Этот профиль использует реальные данные и серверные шаблоны; оплачиваемая модель проверяется отдельным ограниченным прогоном.

Проверочные запросы: «Я рядом с EXPO, пюре с котлетой очень дёшево»; затем «Поближе пожалуйста»; «Просто где поесть рядом»; «Какой маршрут у RedBus?»; «Где сесть на RedBus?»; «Последний рейс RedBus сегодня во сколько?». Отсутствие подтверждения блюда или расписания должно быть явно названо.
"""
    body=re.sub(r"\b\d{1,3}(?:,\d{3})+\b",lambda m:m.group().replace(",","\u202f"),body)
    (ROOT/"docs/catalog_refresh_2026-10-19.md").write_text(body)
    print(json.dumps({k:summary[k] for k in ("snapshot_version","canonical_records","new_rich_branches","rich_counts",
        "records_missing_any_applicable_field","without_new_reviewed_rich_facts","new_confirmed_closed_exclusions")},ensure_ascii=False))


if __name__=="__main__":main()
