import React from 'react';
import {MapPin, Ticket, Clock3} from 'lucide-react';
import {t as tr, getLanguage} from '../i18n';
import '../services.css';

const TYPES = {bus_tour: 'Автобусная экскурсия', walking_tour: 'Пешая экскурсия', river_cruise: 'Речная прогулка',
  guided_museum: 'Экскурсия в музее', cultural_activity: 'Культурная программа', city_tour: 'Экскурсия по городу'};
const LABELS = {duration_minutes: 'Продолжительность', river_segment_minutes: 'На воде', address: 'Адрес',
  languages: 'Языки', included: 'Включено', activities: 'В программе', group_minimum: 'Минимальная группа',
  group_size: 'Размер группы', price_formula: 'Полная стоимость', season: 'Сезон', venue_hours: 'Часы площадки',
  group_price_text: 'Стоимость группы', route_description: 'Маршрут', child_age_policy: 'Детский билет',
  concession_currency: 'Валюта льготного билета', other_undated_schedule: 'Расписание', legacy_stop_table: 'Другие остановки',
  boarding_minutes_before_departure: 'Посадка до отправления', boarding_queue: 'Порядок посадки', seat_reservation: 'Бронь мест',
  ticket_sales: 'Где купить билет', confirm_schedule: 'Уточнение расписания', booking_contact: 'Запись и вопросы',
  advance_booking: 'Предварительная запись', advance_booking_required: 'Бронь обязательна',
  advance_booking_conflict: 'Предварительная запись', suggested_start_times: 'Время по согласованию',
  suggested_time_window: 'Время по согласованию'};
const LANGUAGES = {ru: 'Русский', kk: 'Казахский', en: 'Английский'};
const STOP_ROLES = {boarding: 'Посадка', visit: 'Посещение', pass_by: 'Проезжаем мимо, посадка не подтверждена'};

function webUrl(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}

function factValue(fact) {
  if (fact.field === 'languages') return (Array.isArray(fact.value) ? fact.value : [fact.value])
    .map(value => tr(LANGUAGES[value] || value)).join(', ');
  const value = Array.isArray(fact.value) ? fact.value.join(fact.unit === 'minutes' ? '–' : ', ') :
    typeof fact.value === 'boolean' ? tr(fact.value ? 'Да' : 'Нет') : fact.value;
  return fact.unit === 'minutes' ? `${value} ${tr('мин')}` : value;
}

function formatPrice(offer) {
  const amount = new Intl.NumberFormat(getLanguage() === 'en' ? 'en-US' : 'ru-RU').format(offer.amount);
  return `${amount} ${offer.currency === 'KZT' ? '₸' : offer.currency}`;
}

function unitLabel(offer) {
  if (offer.unit === 'per_group') return tr('за группу');
  if (offer.unit === 'per_person_group_size') return tr('с человека в группе из {count}', {count: offer.group_size});
  return tr('с человека');
}

function collectSources(service) {
  const sources = new Map();
  function visit(value) {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) { value.forEach(visit); return; }
    const url = webUrl(value.source_url);
    if (url && !sources.has(url)) sources.set(url, {...value, source_url: url});
    Object.values(value).forEach(visit);
  }
  visit(service);
  return [...sources.values()];
}

function checkedDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat({ru: 'ru-RU', kk: 'kk-KZ', en: 'en-GB'}[getLanguage()],
    {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Asia/Almaty'}).format(date);
}

export default function ServiceCard({service}) {
  const offers = (service.ticket_offers || []).filter(offer => offer.status === 'confirmed');
  const routes = service.routes || [];
  const boardings = new Map();
  for (const route of routes) for (const stop of route.stops || []) {
    if (stop.role === 'boarding' && !boardings.has(stop.id)) boardings.set(stop.id, stop);
  }
  const facts = [...(service.facts || []), ...(service.booking_rules || [])];
  const confirmed = facts.filter(fact => fact.status === 'confirmed' && LABELS[fact.field]);
  const conflicts = facts.filter(fact => fact.status === 'conflicting');
  const uncertainOffers = (service.ticket_offers || []).some(offer => offer.status !== 'confirmed');
  const sources = collectSources(service);
  const departures = service.departures_today || [];
  return <article className="service-card" data-service-id={service.id}>
    <header><span><Ticket size={15} />{tr(TYPES[service.kind] || 'Экскурсия')}</span><h3>{service.name}</h3></header>
    {offers.length > 0 && <ul className="service-fares">{offers.map(offer => <li key={offer.id}>
      <div><strong>{offer.name}</strong><span>{formatPrice(offer)} <small>{unitLabel(offer)}</small></span></div>
      <p>{offer.audience}</p>{offer.notes && <p className="service-fare-note">{offer.notes}</p>}
    </li>)}</ul>}
    {boardings.size > 0 && <section className="service-boarding" aria-label={tr('Где сесть')}>
      <h4><MapPin size={15} />{tr('Где сесть')}</h4>
      {[...boardings.values()].map(stop => <p key={stop.id}>{stop.name}{webUrl(stop.map_url) && <a href={webUrl(stop.map_url)} target="_blank" rel="noreferrer">{tr('Место посадки на карте')}</a>}</p>)}
    </section>}
    <p className="service-schedule"><Clock3 size={15} />{departures.length
      ? `${tr('Подтверждённые отправления')}: ${departures.map(departure => departure.time?.slice(0, 5)).filter(Boolean).join(', ')}`
      : tr(service.schedule_status === 'on_request' ? 'Дата и время по предварительному согласованию.' : 'Отправления на сегодня не подтверждены.')}</p>
    {(conflicts.length > 0 || uncertainOffers) && <p className="service-warning">{tr('Некоторые условия требуют уточнения у оператора.')}</p>}
    {(service.notes || []).map((note, index) => <p className="service-note" key={index}>{note}</p>)}
    {routes.length > 0 && <details className="service-routes">
      <summary>{tr('Маршруты')}: {routes.map(route => route.name || tr('Маршрут')).join(', ')}</summary>
      <p className="service-route-note">{tr('Объект по пути не означает место посадки.')}</p>
      {routes.map((route, index) => <section key={route.id || index} data-route-id={route.id}>
        <h4>{route.name || tr('Маршрут')}</h4>
        {(route.stops || []).length > 0 && <ol>{route.stops.map((stop, stopIndex) =>
          <li key={stop.id || stopIndex} data-stop-role={stop.role}><span>{stop.name}</span>
            <small>{tr(STOP_ROLES[stop.role] || 'Назначение точки не подтверждено')}</small>
          </li>)}</ol>}
      </section>)}
    </details>}
    {(confirmed.length > 0 || conflicts.length > 0) && <details className="service-details"><summary>{tr('Условия и детали')}</summary>
      <dl>{confirmed.map((fact, index) => <div key={fact.field + index}><dt>{tr(LABELS[fact.field])}</dt><dd>{factValue(fact)}{fact.notes && <small>{fact.notes}</small>}</dd></div>)}</dl>
      {conflicts.length > 0 && <section className="service-conflicts"><h4>{tr('Уточни у оператора')}</h4>{conflicts.map((fact, index) => <p key={fact.field + index}>
        {LABELS[fact.field] && <strong>{tr(LABELS[fact.field])}: </strong>}{factValue(fact)}{fact.notes && <small>{fact.notes}</small>}
      </p>)}</section>}
    </details>}
    {sources.length > 0 && <details className="service-sources"><summary>{tr('Источники и дата проверки')}</summary><ul>{sources.map(source => <li key={source.source_url}>
      <a href={source.source_url} target="_blank" rel="noreferrer">{new URL(source.source_url).hostname.replace(/^www\./, '')}{new URL(source.source_url).pathname}</a>
      {checkedDate(source.checked_at) && <time dateTime={source.checked_at}>{tr('Проверено')}: {checkedDate(source.checked_at)}</time>}
    </li>)}</ul></details>}
  </article>;
}
